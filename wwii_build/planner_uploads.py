"""Bounded planner uploads and multipart parsing.

Uploads are immutable user context. They live under the manager state directory,
never in a task worktree or the integration branch. Jev must select an upload
before it enters a planner prompt or a provider invocation.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path

from .config import Config
from .db import DB
from .models import iso, utcnow

MAX_FILES = 8
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_TOTAL_BYTES + 2 * 1024 * 1024
MAX_TEXT_EXCERPT_BYTES = 24 * 1024

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".xml", ".html", ".css", ".js", ".ts", ".tsx", ".jsx", ".py", ".rs", ".c", ".h", ".cpp",
    ".hpp", ".java", ".kt", ".kts", ".cs", ".go", ".sql", ".cypher", ".sh", ".zsh", ".ini",
    ".cfg", ".log",
}
IMAGE_MAGIC = {
    "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
    "image/webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}


class PlannerUploadError(ValueError):
    pass


@dataclass(frozen=True)
class IncomingUpload:
    field_name: str
    filename: str
    media_type: str
    data: bytes


def parse_post_body(content_type: str, body: bytes) -> tuple[dict[str, list[str]], list[IncomingUpload]]:
    """Parse urlencoded or multipart form data without the removed ``cgi`` module."""
    if len(body) > MAX_REQUEST_BYTES:
        raise PlannerUploadError("הבקשה גדולה מדי; המגבלה הכוללת היא 25MB של קבצים")
    if not content_type.lower().startswith("multipart/form-data"):
        import urllib.parse
        try:
            return urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True), []
        except UnicodeDecodeError as exc:
            raise PlannerUploadError("טופס לא תקין") from exc

    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    if not message.is_multipart():
        raise PlannerUploadError("טופס העלאה לא תקין")
    fields: dict[str, list[str]] = {}
    uploads: list[IncomingUpload] = []
    for part in message.iter_parts():
        field = part.get_param("name", header="content-disposition")
        if not field:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            if payload or filename:
                uploads.append(IncomingUpload(str(field), str(filename),
                                               part.get_content_type() or "application/octet-stream", payload))
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            value = payload.decode(charset, "strict")
        except (LookupError, UnicodeDecodeError):
            value = payload.decode("utf-8", "replace")
        fields.setdefault(str(field), []).append(value)
    validate_uploads(uploads)
    return fields, uploads


def _safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name.strip().replace("\x00", "")
    name = re.sub(r"[^\w.()\- א-ת]", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:140] or "file"


def _image_media(data: bytes) -> str | None:
    return next((media for media, valid in IMAGE_MAGIC.items() if valid(data)), None)


def _looks_text(name: str, media_type: str, data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return False
    return (media_type.startswith("text/") or Path(name).suffix.lower() in TEXT_SUFFIXES or
            media_type in {"application/json", "application/xml", "application/yaml", "application/toml"})


def validate_uploads(uploads: list[IncomingUpload]) -> None:
    if len(uploads) > MAX_FILES:
        raise PlannerUploadError(f"אפשר לצרף עד {MAX_FILES} קבצים בכל בקשה")
    total = 0
    for upload in uploads:
        if not upload.filename.strip():
            raise PlannerUploadError("לקובץ מצורף חסר שם")
        size = len(upload.data)
        if size == 0:
            raise PlannerUploadError(f"הקובץ {upload.filename} ריק")
        if size > MAX_FILE_BYTES:
            raise PlannerUploadError(f"הקובץ {upload.filename} גדול מ־10MB")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise PlannerUploadError("סך הקבצים גדול מ־25MB")


def store(db: DB, cfg: Config, plan_task_id: str, uploads: list[IncomingUpload]) -> list[dict]:
    validate_uploads(uploads)
    root = cfg.state_dir / "planner_uploads" / plan_task_id.replace("/", "__")
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    now = iso(utcnow())
    records: list[dict] = []
    for upload in uploads:
        digest = hashlib.sha256(upload.data).hexdigest()
        safe = _safe_name(upload.filename)
        image_media = _image_media(upload.data)
        kind = "image" if image_media else ("text" if _looks_text(safe, upload.media_type, upload.data) else "file")
        media_type = image_media or upload.media_type or mimetypes.guess_type(safe)[0] or "application/octet-stream"
        item_dir = root / digest[:16]
        item_dir.mkdir(parents=True, exist_ok=True)
        item_dir.chmod(0o700)
        path = item_dir / safe
        if not path.exists():
            path.write_bytes(upload.data)
            path.chmod(0o600)
        excerpt = None
        if kind == "text":
            excerpt = upload.data[:MAX_TEXT_EXCERPT_BYTES].decode("utf-8", "replace")
        attachment_id = db.x(
            "INSERT INTO planner_attachments(plan_task_id,original_name,stored_path,media_type,kind,size_bytes,"
            "sha256,text_excerpt,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (plan_task_id, safe, str(path), media_type, kind, len(upload.data), digest, excerpt, now))
        records.append({"id": attachment_id, "name": safe, "path": str(path), "media_type": media_type,
                        "kind": kind, "size_bytes": len(upload.data), "sha256": digest})
    if records:
        row = db.task(plan_task_id)
        extra = json.loads(row["extra"] or "{}")
        extra["attachments"] = records
        db.x("UPDATE tasks SET extra=? WHERE task_id=?", (json.dumps(extra, ensure_ascii=False), plan_task_id))
        db.event("PLANNER_FILES_UPLOADED", task_id=plan_task_id, count=len(records),
                 bytes=sum(item["size_bytes"] for item in records),
                 kinds={kind: sum(item["kind"] == kind for item in records) for kind in ("image", "text", "file")})
    return records


def candidates(db: DB, plan_task_id: str) -> list[dict]:
    out = []
    for row in db.q("SELECT * FROM planner_attachments WHERE plan_task_id=? ORDER BY id", (plan_task_id,)):
        excerpt = row["text_excerpt"] or (
            f"קובץ מצורף {row['original_name']} מסוג {row['media_type']} ובגודל {row['size_bytes']} בתים. "
            "הנתיב המקומי מופיע ב-origin_ref; השתמש בו רק אם הקובץ נבחר על ידי Jev.")
        decision_hint = re.sub(r"\s+", " ", (row["text_excerpt"] or "")).strip()[:350]
        out.append({
            "id": f"upload:{row['id']}:{row['sha256'][:12]}",
            "source_key": f"planner-upload:{row['id']}",
            "description": (f"קובץ שהמשתמש צירף · {row['original_name']} · {row['media_type']} · "
                            f"{row['size_bytes']} bytes" + (f" · התחלה: {decision_hint}" if decision_hint else "")),
            "execution_kind": "planner_upload", "excerpt": excerpt,
            "origin_kind": "planner_upload", "origin_ref": row["stored_path"],
            "graph_entity_id": None, "content_sha256": row["sha256"], "title": row["original_name"],
            "attachment_id": row["id"], "attachment_kind": row["kind"], "media_type": row["media_type"],
            "size_bytes": row["size_bytes"],
        })
    return out


def mark_selected(db: DB, selected: list[dict]) -> None:
    ids = [int(item["attachment_id"]) for item in selected if item.get("origin_kind") == "planner_upload"
           and item.get("attachment_id")]
    if not ids:
        return
    now = iso(utcnow())
    for attachment_id in ids:
        db.x("UPDATE planner_attachments SET selected_at=? WHERE id=?", (now, attachment_id))
