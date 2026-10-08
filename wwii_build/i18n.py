"""Dashboard localisation (English source strings -> Hebrew).

Only whole UI text nodes are translated; ids, paths, model names and log text are left
as they are (and rendered LTR inside the RTL page).
"""
from __future__ import annotations

import re

HE: dict[str, str] = {
    # header / status
    "WWII Build Manager": "מנהל הבנייה — מלחמת העולם השנייה",
    "EMERGENCY STOP": "עצירת חירום", "PAUSED": "מושהה", "RUNNING": "רץ", "DAEMON NOT RUNNING": "ה־daemon לא פועל",
    "daemon pid": "daemon pid", "wave": "גל", "next wakeup": "התעוררות הבאה",
    "PAUSE": "השהה", "RESUME": "המשך", "STOP": "עצור", "Advanced": "מתקדם",
    "Pause + interrupt running": "השהה ועצור את הרצות", "EMERGENCY KILL": "עצירת חירום מיידית",
    "Clear emergency + resume": "נקה מצב חירום והמשך",
    "+ New task": "+ משימה חדשה", "Prompt → tasks": "פרומפט ← משימות", "English": "אנגלית", "עברית": "עברית",
    "restart required": "נדרשת הפעלה מחדש",
    # counts
    "completed": "הושלמו", "running": "רצות", "ready": "מוכנות", "waiting": "ממתינות", "repairing": "בתיקון",
    "review": "לבדיקה", "blocked": "חסומות", "failed": "נכשלו", "cancelled": "בוטלו",
    # sections
    "Overview": "סקירה", "Current workers": "עובדים פעילים", "Waiting for you": "ממתין לך", "Quotas": "מכסות",
    "Latest artifacts": "תוצרים אחרונים", "Tasks": "משימות",
    "Capability gaps & cross-domain requests": "פערי יכולת ובקשות בין־תחומיות",
    "Capability gaps &amp; cross-domain requests": "פערי יכולת ובקשות בין־תחומיות",
    "event log": "יומן אירועים", "Event log": "יומן אירועים", "api/state": "api/state",
    # table headers
    "task": "משימה", "provider": "ספק", "model": "מודל", "runtime": "זמן ריצה", "PID": "PID", "context": "קונטקסט",
    "worktree": "worktree", "#": "#", "kind": "סוג", "subject": "נושא", "reason": "סיבה", "family": "משפחה",
    "status": "מצב", "used": "נוצל", "session reset": "איפוס session", "weekly reset": "איפוס שבועי",
    "blocked until": "חסום עד", "source": "מקור", "session used": "ניצול session (5 שע׳)",
    "weekly used": "ניצול שבועי", "updated": "עודכן", "owner": "בעלים", "state": "מצב", "id": "id", "time": "זמן",
    "failure": "כשל", "tokens in/cached/out": "טוקנים נכנס/cache/יצא", "cost (reported)": "עלות (מדווחת)",
    "pid": "pid", "logs": "לוגים",
    # empty states
    "no workers running": "אין עובדים פעילים", "nothing waiting for you": "אין משהו שממתין לך",
    "no data yet (unknown)": "אין נתונים עדיין (לא ידוע)", "none yet": "אין עדיין", "none reported": "לא דווחו",
    "none": "אין", "not run yet": "לא הורץ עדיין", "not built yet": "לא נבנה עדיין", "not started": "לא התחיל",
    "unknown": "לא ידוע", "model profiles": "פרופילי מודלים", "no acceptance run": "לא הורצה בדיקת קבלה",
    # buttons
    "Approve": "אשר", "Reject": "דחה", "Retry": "נסה שוב", "Skip": "דלג", "Re-run acceptance": "הרץ קבלה מחדש",
    "Change provider": "החלף ספק", "same route": "אותו מסלול", "note": "הערה", "Create task": "צור משימה",
    "Send to planner": "שלח למתכנן", "refresh codex": "רענן codex", "refresh claude": "רענן claude",
    "I did a codex usage reset in the app": "ביצעתי reset למכסת Codex באפליקציה",
    "I did a claude usage reset in the app": "ביצעתי reset למכסת Claude באפליקציה",
    # task page
    "← overview": "← סקירה", "Dependencies": "תלויות", "Write scope": "תחום כתיבה", "Handoff": "Handoff",
    "Attempts": "ניסיונות", "Artifacts": "תוצרים", "Tests": "בדיקות", "Diff": "Diff",
    "Context supplied (latest attempt)": "קונטקסט שנשלח (ניסיון אחרון)", "Brief": "Brief",
    "none (root)": "אין (שורש)", "Repair chain": "שרשרת תיקונים", "Instructions": "הוראות",
    # forms
    "New task": "משימה חדשה", "Title": "כותרת", "Short id (optional)": "מזהה קצר (לא חובה)",
    "What should the worker do?": "מה העובד צריך לעשות?", "Model": "מודל",
    "allow fallback to the routing chain if this model is unavailable":
        "אפשר מעבר לשרשרת הניתוב אם המודל לא זמין",
    "Owner": "בעלים", "(new owner for this task)": "(בעלים חדש למשימה זו)",
    "Write scope (one path per line; directories end with /)": "תחום כתיבה (נתיב בכל שורה; תיקייה מסתיימת ב־/)",
    "read-only (report only; the manager files it)": "קריאה בלבד (דוח; המנהל שומר אותו)",
    "Context files (inlined in the prompt)": "קובצי קונטקסט (נכנסים לפרומפט)",
    "More context paths (one per line)": "נתיבי קונטקסט נוספים (נתיב בכל שורה)",
    "Reference paths (listed, not inlined)": "נתיבי עיון (רשומים, לא נכנסים לפרומפט)",
    "MCP servers": "שרתי MCP",
    "Only servers of the chosen model's provider are used. Nothing is enabled unless you tick it.":
        "רק שרתים של הספק של המודל שנבחר יופעלו. שום שרת לא מופעל אם לא סימנת אותו.",
    "Acceptance commands (one shell command per line)": "פקודות קבלה (פקודת shell בכל שורה)",
    "Without an acceptance command the task ends in REVIEW_REQUIRED for your approval.":
        "בלי פקודת קבלה המשימה תסתיים ב־REVIEW_REQUIRED לאישורך.",
    "writes": "כותב", "no servers configured": "אין שרתים מוגדרים",
    "Describe the work": "תאר את העבודה", "Planner model": "מודל מתכנן",
    "default (strong planner in routing PLAN)": "ברירת מחדל: Sol בחשיבה גבוהה, Sonnet כגיבוי",
    "A cheap model turns the prompt into a proposal of tasks and dependencies. Nothing is created until you approve it.":
        "מודל זול הופך את הפרומפט להצעת משימות ותלויות. שום דבר לא נוצר עד שתאשר.",
    "Plan requests": "בקשות תכנון", "Proposed tasks": "משימות מוצעות", "key": "מפתח", "title": "כותרת",
    "deps": "תלויות", "scope": "תחום", "checks": "בדיקות", "read-only": "קריאה בלבד", "validation": "אימות",
    "created": "נוצרו", "View what was created": "צפה במה שנוצר", "Summary": "סיכום", "Visual": "ויזואלי",
    "Code": "קוד", "Decide": "החלטה", "No visual output in this change": "אין תוצר ויזואלי בשינוי הזה",
    "output": "פלט",
}

STATES_HE = {
    "PENDING": "ממתין", "READY": "מוכן", "WAITING_DEPENDENCY": "ממתין לתלות", "WAITING_PROVIDER": "ממתין לספק",
    "WAITING_QUOTA": "ממתין למכסה", "WAITING_APPROVAL": "ממתין לאישור", "RUNNING": "רץ", "PAUSING": "משהה",
    "PAUSED": "מושהה", "CODE_READY": "קוד מוכן", "WAITING_REPAIR": "ממתין לתיקון",
    "ARCHITECTURE_REVIEW_REQUIRED": "נדרשת בדיקת ארכיטקטורה", "REVIEW_REQUIRED": "נדרשת בדיקה", "REVIEWING": "בבדיקה",
    "PASSED": "עבר", "FAILED": "נכשל", "BLOCKED": "חסום", "CANCELLED": "בוטל", "SUCCEEDED": "הצליח",
    "FAILED_ATTEMPT": "ניסיון נכשל", "QUOTA_LIMITED": "הוגבל במכסה", "CRASHED": "קרס", "INTERRUPTED": "נקטע",
    "AVAILABLE": "זמין", "NEAR_LIMIT": "קרוב לגבול", "UNKNOWN": "לא ידוע", "AUTH_ERROR": "שגיאת התחברות",
    "BLOCKED_SESSION": "חסום (session)", "BLOCKED_WEEKLY": "חסום (שבועי)", "BLOCKED_UNKNOWN": "חסום",
    "CATALOG": "בקטלוג", "MISSING_CREDENTIAL": "חסר מפתח", "AUTH_FAILED": "האימות נכשל",
    "API_UNREACHABLE": "השירות אינו נגיש", "RATE_LIMITED": "הגעת למגבלת קצב", "NO_CREDITS": "אין יתרה",
    "INVALID_RESPONSE": "תשובה לא תקינה", "SELECTED": "נבחר", "UNPRICED": "טרם תומחר", "PRICED": "מתומחר",
    "NOT_CHECKED": "טרם נבדק", "HEALTHY": "תקין",
}

_NODE = re.compile(r">(\s*)([^<>]+?)(\s*)<")


def t(text: str, lang: str) -> str:
    if lang != "he":
        return text
    return HE.get(text, text)


def catalog() -> dict:
    """Every UI string for the browser client. English source strings are the keys, so "en" is the identity map."""
    return {"default": "he", "dir": {"he": "rtl", "en": "ltr"},
            "strings": {"he": dict(HE), "en": {k: k for k in HE}},
            "states": {"he": dict(STATES_HE), "en": {k: k for k in STATES_HE}}}


def state_label(state: str, lang: str) -> str:
    return STATES_HE.get(state, state) if lang == "he" else state


def localize(html: str, lang: str) -> str:
    """Translate whole text nodes that match a known UI string."""
    if lang != "he":
        return html

    def sub(m):
        txt = m.group(2)
        return ">" + m.group(1) + HE.get(txt, txt) + m.group(3) + "<"
    return _NODE.sub(sub, html)
