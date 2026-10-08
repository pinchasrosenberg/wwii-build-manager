"""Hebrew, source-backed explanations for tasks and Deliver implementations.

These are views over current definitions and runtime records, not historical claims.
They are recomputed when pages/API responses are read, so a changed Deliver never
keeps an old implementation summary.
"""
from __future__ import annotations

import json
from functools import lru_cache


LEGACY_MANUAL_HE = {
    "MANUAL/plan2-plan2-resume-running": "בודקת שהעבודות שכבר החלו ממשיכות ומסיימות את שלבי הביצוע שלהן.",
    "MANUAL/plan2-plan2-resume-command": "משלימה את שלב מבנה הפיקוד ומוודאת שתוצריו זמינים למשימות התלויות בו.",
    "MANUAL/plan2-plan2-resume-ready-foundations": "מפעילה מחדש משימות יסוד שמוכנות להרצה ובודקת שהן מתקדמות.",
    "MANUAL/plan2-plan2-unblock-dependent-runs": "בודקת תלויות שהושלמו ומשחררת את המשימות שממתינות להן.",
    "MANUAL/plan2-plan2-final-integration": "מבצעת שילוב סופי ובודקת שמירה, שחזור והרצה חוזרת של התוצרים.",
}

LEGACY_DELIVER_HE = {
    ("episode.context_scan", "Extract bounded weather, place, date, battle and graph signals from the current episode state."):
        "מחלץ ממצב האפיזודה נתונים תחומים על מזג האוויר, המקום, הזמן, הקרב והגרף.",
    ("presentation.snow_visual_audio", "Produce VR-ready snow visuals and audio from simulation state without making presentation authoritative."):
        "יוצר מראה וקול של שלג מתוך מצב הסימולציה, עם התאמה עתידית ל־VR, בלי להפוך את התצוגה למקור האמת.",
    ("simulation.snow_mobility", "Apply variant-aware traction, speed, fatigue and logistics effects without changing historical identities."):
        "מחשב כיצד תנאי שלג משפיעים על אחיזה, מהירות, עייפות ולוגיסטיקה לפי גרסת הציוד, בלי לשנות זהויות היסטוריות.",
    ("simulation.snow_visibility", "Apply bounded perception, spotting and engagement modifiers derived from active snow conditions."):
        "מחשב כיצד מצב השלג משפיע על ראות, זיהוי מטרות והיתקלות, בתוך גבולות מוגדרים.",
    ("terrain.snow_surface_build", "Create snow coverage, compaction, tracks, thaw/freeze and surface parameters from SnowState."):
        "בונה מתוך מצב השלג כיסוי, הידוק, עקבות, הפשרה וקיפאון ונתוני פני שטח.",
    ("weather.snow_research", "Resolve snow type, depth/range, timing, surface condition and uncertainty from scoped historical evidence."):
        "בודק ראיות היסטוריות ממוקדות כדי לקבוע סוג שלג, עומק או טווח, תזמון, מצב הקרקע ואי־ודאות.",
    ("weather.snow_state_compile", "Normalize evidence into SnowState without inventing unknown depth, timing or confidence."):
        "מארגן את הראיות למצב שלג אחיד בלי להמציא עומק, תזמון או רמת ודאות שאינם ידועים.",
}


@lru_cache(maxsize=4)
def _purposes(path: str, mtime_ns: int) -> dict[str, str]:
    with open(path, encoding="utf-8") as source:
        registry = json.load(source)
    return {item["lego_id"]: item.get("purpose_he", "") for item in registry.get("items", [])}


def _hebrew(value: str) -> bool:
    return any("\u0590" <= ch <= "\u05ff" for ch in value)


def task_he(cfg, task) -> str:
    extra = json.loads(task["extra"] or "{}")
    explicit = str(extra.get("description_he") or "").strip()
    if explicit:
        return explicit
    task_id = task["task_id"]
    if task_id in LEGACY_MANUAL_HE:
        return LEGACY_MANUAL_HE[task_id]
    if task["kind"] == "plan":
        prompt = str(extra.get("prompt") or task["title"] or "").strip()
        return "המתכנן מפרק את הבקשה למשימות, תלויות וקונטקסט מתאים." + (f" הבקשה: {prompt[:300]}" if _hebrew(prompt) else "")
    if task["kind"] == "repair":
        return "מתקנת כשל במשימת המקור, מריצה שוב את הבדיקות ומחזירה את העבודה למסלול הביצוע."
    ids = json.loads(task["lego_ids"] or "[]")
    if ids:
        path = cfg.repo / cfg.data["plan"]["registry"]
        try:
            purposes = _purposes(str(path), path.stat().st_mtime_ns)
        except (OSError, ValueError, KeyError):
            purposes = {}
        details = [purposes.get(item, "") for item in ids]
        details = [item.rstrip(".") for item in details if item]
        if details:
            return "המשימה מגדירה ומממשת: " + "; ".join(details) + "."
    note = str(task["note"] or "").strip()
    if _hebrew(note):
        return note
    title = str(task["title"] or "").strip()
    if _hebrew(title):
        return "המשימה מבצעת את העבודה הבאה: " + title
    return "המשימה מבצעת את הוראות העבודה שהוגדרו לה, במסגרת תחום הכתיבה והתלויות המוצגים למטה."


def deliver_description_he(cfg, db, deliver) -> str:
    linked = db.task(deliver["deliver_id"])
    if linked:
        return task_he(cfg, linked)
    description = str(deliver["description"] or "").strip()
    if _hebrew(description):
        return description
    known = LEGACY_DELIVER_HE.get((deliver["deliver_id"], description))
    if known:
        return known
    return "נדרש הסבר בעברית לתפקיד הרכיב." + (f" התיאור הקיים: {description}" if description else "")


def deliver_implementation_he(db, deliver) -> str:
    """Describe actual execution state, references and routing without inventing code."""
    did = deliver["deliver_id"]
    kind = deliver["execution_kind"]
    ref = str(deliver["implementation_ref"] or "").strip()
    task = db.task(did)
    parts = []
    if kind == "deterministic":
        parts.append("מופעל כפונקציה דטרמיניסטית, ללא קריאת מודל בזמן ההרצה.")
    elif kind == "llm_research":
        parts.append("מבצע מחקר ממוקד באמצעות מודל; המקורות שנשלפים נשארים מועמדים עד לבחירת Jev.")
    elif kind == "context_bundle":
        parts.append("אוסף חבילת קונטקסט מתוך מקורות מוגדרים ומעביר רק מקטעים שנבחרו ב־Jev.")
    elif kind == "review":
        parts.append("בודק תוצרים ובדיקות לפני קידום ה־Deliver.")
    else:
        parts.append("מופעל כמשימת בנייה של סוכן לפי חוזה המשימה, הקונטקסט ותלויותיה.")
    if ref.startswith("planned:") or deliver["availability"] == "planned":
        parts.append("המימוש עדיין מתוכנן; לא קיים תוצר מאומת להפעלה.")
    elif ref:
        parts.append(f"מיקום המימוש הרשום: {ref}.")
    if task:
        if task["state"] == "PASSED":
            parts.append("המשימה המקושרת עברה בדיקות וקודמה לענף האינטגרציה.")
        elif task["state"] == "RUNNING":
            parts.append("המימוש נמצא כעת בבנייה.")
        else:
            parts.append("המשימה המקושרת עדיין לא השלימה קידום מאומת.")
        scope = json.loads(task["write_scope"] or "[]")
        if scope:
            parts.append("תחום התוצרים: " + ", ".join(scope[:6]) + (" ועוד" if len(scope) > 6 else "") + ".")
    listeners = db.one("SELECT COUNT(*) n FROM deliver_listener_edges WHERE source_deliver_id=? AND edge_type='listener' AND enabled=1", (did,))
    if listeners and listeners["n"]:
        parts.append(f"מציע {listeners['n']} מאזינים; Jev מחליט אם להפעיל כל אחד מהם לפי מצב הבנייה.")
    return " ".join(parts)
