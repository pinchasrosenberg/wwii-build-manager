# הכנסת מערכות למנהל המשימות (`wwii-build onboard`)

התיקייה הזאת מחזיקה **מניפסט לכל מערכת** שהוכנסה למנהל. מניפסט מתאר את רכיבי המערכת, והפקודה
`wwii-build onboard <name>` הופכת אותו בפעולה אחת, דטרמיניסטית ואידמפוטנטית, ל:

| תוצר | איפה | למה |
|---|---|---|
| קובץ קונטקסט RAG לכל רכיב + מפת מערכת | `context/systems/<system>/*.md` | נכנס ל־CONTEXT INDEX של המתכנן, ועובדים מקבלים אותו כקונטקסט |
| Deliver לכל רכיב | `deliver_catalog` (`source_kind=system_manifest`) | מופיע במרכז ה־Delivers; אפשר לבחור לו מודל, תלויות ומאזינים |
| מקור קונטקסט | `context_sources` (`origin_kind=system_context`) | מועמד שהמתכנן והעובדים מקבלים, תמיד דרך בחירה של Jev |
| גישה לגרף ה־RAG | `deliver_graph_access` | `none` / `limited` / `full` לכל רכיב, עם scope |
| קשתות תלות | `deliver_listener_edges` (`prerequisite`) | מוצגות במפת הקשרים |
| יכולות ותתי־יכולות | `deliver_capabilities` + קטע בקובץ הקונטקסט + עץ בדף ה־Deliver | מתגלות אוטומטית מהקוד לפי כללי `discover` |
| עץ מובנה בגרף ה־RAG | `POST /ingest/structured` בשירות הגרף (ברירת מחדל `:8766`) | `SYSTEM → DELIVER → CAPABILITY → SUBCAPABILITY` + `DEPENDS_ON`, עם embeddings, בלי מודל שפה; נשלח רק כשהעץ השתנה |

הקבצים נוצרים מהמקור עצמו בלי מודל שפה: ראשי README, docstrings וחתימות של Python, הערות פתיחה ושמות
פונקציות ב־JS, הערות בסקריפטי shell, פקודות הפעלה, פורטים וממשקים מהמניפסט. אותו קלט נותן בדיוק אותו
פלט, וגודל כל קובץ מוגבל (20K תווים).

## הוספת מערכת חדשה

1. העתק את `_template.toml` לשם המערכת, למשל `roman_atlas.toml`, ומלא את `[system]` ואת ה־`[[components]]`.
2. תצוגה מקדימה, בלי לכתוב כלום:
   ```bash
   tools/build_manager/bin/wwii-build onboard roman_atlas --dry-run
   ```
3. הכנסה (קבצים, Delivers, מקורות, קליטה לגרף):
   ```bash
   tools/build_manager/bin/wwii-build onboard roman_atlas
   ```
4. מצב:
   ```bash
   tools/build_manager/bin/wwii-build onboard --list
   ```

אחרי שינוי בקוד של מערכת, מריצים שוב את אותה פקודה: הקבצים מתעדכנים, ורק מה שהשתנה נשלח שוב לגרף.
`--no-graph` מדלג על הגרף, `--graph-only` שולח רק לגרף, ו־`--force` (עם `--graph-only`) שולח הכול מחדש.
אותה פעולה זמינה גם ככלי MCP: `system_onboard` ו־`system_onboarding_status`.

## גילוי יכולות (`discover`)

כל כלל מגדיר קבוצת יכולת (`group`) וממנה נגזרות תתי־היכולות:

| `kind` | מה הופך לתת־יכולת |
|---|---|
| `files` | כל קובץ שתואם ל־`glob`, עם התיאור מה־docstring או מהערת הפתיחה |
| `py_functions` | פונקציות ציבוריות ברמה העליונה, עם השורה הראשונה של ה־docstring |
| `mcp_tools` | פונקציות עם decorator של `tool` (כלי MCP) |
| `http_routes` | נתיבי HTTP: decorators של FastAPI/Flask, השוואות `path == "/x"` ו־`path.startswith("/x")` |
| `argparse` | פקודות `add_parser(...)` עם ה־help שלהן |
| `js_functions` | פונקציות JS מיוצאות או מוגדרות ברמה העליונה |

`exclude` מקבל שמות קבצים להוצאה (למשל `["__init__.py"]`). אפשר להוסיף גם `capabilities = [{group, name,
description}]` ליכולות שאי אפשר לגלות מהקוד, כמו פקודות צ'אט.

הקליטה הישנה של טקסט חופשי דרך ה־LLM של שירות הגרף כבויה כברירת מחדל, כי היא איטית ומאבדת טקסט. אפשר
להפעיל אותה עם `graph_text = true` ב־`[system]`, או עם `--graph-only --text`.

## כללים לכתיבת מניפסט

- `deliver_id`: אותיות קטנות, ספרות, `.`, `_`, `-`, `/`. קידומת המערכת (`ww2.`) מונעת התנגשויות.
- `root`: נתיב יחסי למאגר (עובדים יכולים לכתוב בו) או מוחלט/`~` (ידע וקונטקסט בלבד). כשרכיב קיים גם
  במאגר וגם בחוץ, הפנה לעותק שמפותח כאן.
- `docs` ו־`code` הם globs יחסיים ל־`root`. תיקיות כבדות (`node_modules`, `.venv`, `__pycache__`, `_bak*`
  ועוד) מדולגות, ועד 40 קבצים לרכיב.
- `execution_kind`: `worker` (פיתוח על ידי עובד), `deterministic` (קוד קיים שרץ בלי מודל), `llm_research`,
  `asset_pipeline`. `availability`: `available`, `prototype`, `planned`.
- `depends_on` חייב להצביע על Deliver קיים, מאותו מניפסט או מהקטלוג (למשל `B00/contracts`).
- אל תכניס סודות למניפסט. הוא נשמר במאגר, והקבצים שנוצרים נשלחים לגרף.

## תבניות שרשרת הקרב

`battle_request_templates.toml` אינו מניפסט של מערכת: הוא מתאר את חמשת שלבי שרשרת בונה הקרבות שנוצרת בבקשת
קרב אחת (`wwii-build battle-request`, כלי MCP `battle_request`, הטופס "בקשת קרב"). עורכים אותו בלי שינוי קוד;
`onboard --list` מדלג עליו. פירוט בקובץ עצמו ובפרק "משימה ידנית" ב־README של המנהל.

## מערכות קיימות

| מניפסט | מערכת |
|---|---|
| `ww2_atlas.toml` | אטלס וסימולציית מלחמת העולם השנייה: 15 רכיבים, 42 יכולות, 548 תתי־יכולות |
