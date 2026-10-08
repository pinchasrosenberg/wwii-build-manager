# WWII Build Manager (`wwii-build`)

מנהל בנייה מקומי ודטרמיניסטי: לוקח את גרף העבודה הקיים (`dispatch_tasks` ב־`docs/game/LEGO_OWNERSHIP_REGISTRY.json`), מריץ בעצמו את Codex CLI ואת Claude Code CLI על משימות תחומות, מנהל תלויות, בעלות, מכסות, fallback ואישורים, ומציג הכול ב־dashboard מקומי.

```
The plan defines the work.  The scheduler moves the work.  Models execute scoped tasks.
Tests decide what passed.   Quota decides when/where.      You can stop everything at any moment.
```

אין LLM שמנהל את התור. מודל נקרא רק כדי לבצע משימה; בחירת משימה, מודל, קונטקסט, קבלה ו־retry הן קוד.

**בחירת מודל היא לפי התאמה בלבד.** לכל פרופיל משימה יש טבלת `fit` (ציון 0–10 לכל מודל, ב־`config.py`) והשרשרת היא המודלים ממוינים לפי הציון, בלי קשר לספק (Codex/Claude). רק מודל שמתאים באמת לפרופיל מופיע בו. שוויון ציונים נשבר לפי דרגת עלות (זול קודם), אחר כך לפי מכסה פנויה, ורק אז לפי שם. מכסה משמשת רק לסינון ולשבירת שוויון. אפשר לשנות ציון ב־`[fit.<PROFILE>]` או לקבע סדר לפרופיל אחד ב־`[routing]`. משימה ידנית ותכנון ללא מודל נבחר מנותבים אוטומטית ("אוטומטי: המודל המתאים ביותר").

## התקנה

דרישות: macOS, Python ≥ 3.11 (stdlib בלבד — אין pip install), git, ו־Codex CLI / Claude Code CLI מחוברים לחשבונות שלך.

```bash
ln -s "$PWD/bin/wwii-build" ~/.local/bin/wwii-build   # מתוך שורש המאגר
wwii-build config init        # יוצר .wwii-build/config.toml מתוך config.example.toml
```

בלי symlink: `tools/build_manager/bin/wwii-build <command>` או `PYTHONPATH=tools/build_manager python3 -m wwii_build <command>`.

## הפעלה ראשונה

```bash
wwii-build doctor         # git, python, sqlite, CLIs, גרסאות, flags, auth, מודלים, פורט. בלי inference.
wwii-build import-plan    # מייבא את 28 ה־dispatch_tasks מהרישום (אידמפוטנטי)
wwii-build dry-run        # מה ירוץ עכשיו, על איזה provider/model, עם איזה קונטקסט ולמה. בלי בקשת LLM.
wwii-build baseline       # פעם אחת: יוצר את ענף wwii-build/integration (ראה למטה)
wwii-build start          # scheduler בחזית + dashboard ב־http://127.0.0.1:8765
```

אם רוצים שהאתר יישאר פתוח גם כשהמתזמן נעצר, מפעילים בחלון נפרד
`wwii-build dashboard --persistent` ואז `wwii-build start --no-dashboard`.
הדשבורד ממתין לפורט כשמופע אחר מחזיק אותו ומתחבר כשמתפנה.

**אפליקציית הדפדפן החיה:** `http://127.0.0.1:8765/` מגיש אפליקציה ללא רענון דף (`wwii_build/static/app/`: ES modules, בלי build ובלי תלויות). היא מתחברת ל־`/ws`, נרשמת לנושאי הדף, מקבלת snapshot/patch ושולחת פעולות כ־`{"type":"action"}` (התשובה מוצגת כ־toast). פעולות ארוכות (`unstick`, ‏`system_onboard` עם `manifest`/`graph`, ‏`state_chat`, ‏`graph_console_query`) רצות ב־worker thread ודוחפות `{"type":"progress","id","line"}` לפני ה־`action.result` (ב־`state_chat` השורה הראשונה היא `thinking`, וההודעה נכנסת לנושא `chat:<id>` של כל הלקוחות הפתוחים עוד לפני התשובה); בלקוח מוצג פאנל התקדמות חי לכל פעולה והכפתור מושבת בזמן הריצה. `unstick` ו־`system_onboard` רצים אחד בכל פעם — בקשה שנייה מקבלת `ok=false` עם `כבר רץ` (גם בטפסי ה־HTML הקלאסיים). ניתוק מציג "מתחבר מחדש…" וחיבור מחדש שולח את ה־revs הקיימים. כל דפי המנהל (`#/`, ‏`#/delivers`, ‏`#/deliver`, ‏`#/task`, ‏`#/events`, ‏`#/rag`, ‏`#/plan`, ‏`#/new`, ‏`#/subtasks`) חיים באפליקציה. הדפים המורנדרים בשרת נשארים כגיבוי סטטי תחת `http://127.0.0.1:8765/classic/…` (כל הנתיבים הישנים, כולל הטפסים שנשלחים ל־`/action`, ממשיכים לעבוד שם). **הם אינם מתרעננים מעצמם** — הרענון כל 6 שניות הוסר; בראש כל דף קלאסי יש באנר עם קישור לאפליקציה החיה, ורענון ידני הוא F5. הארכיטקטורה, הפרוטוקול והאבטחה מתועדים בסעיף "אפליקציה חיה: ארכיטקטורת socket" למטה. הקבצים מוגשים תחת `/app/<file>` בלבד, עם נתיב בטוח וללא רשימת תיקייה; הטוקן מוזרק ל־`index.html` בזמן ההגשה. בדיקות הלקוח: `tests/js/*.test.mjs` (node ‏≥22.7, רצות מתוך `test_app_shell.py` ונדלגות כשאין node).

בדיקת מודלים יומית קוראת את דפי המודלים הרשמיים של OpenAI ו־Anthropic ללא בקשת inference.
היא מעדכנת אוטומטית פרופילים מקבילים מסוג Sol, Luna, Sonnet ו־Haiku בלבד; דגם Codex
חייב להופיע גם ברשימה המקומית של ה־CLI. בחירה מפורשת ב־`config.toml` נשארת קבועה,
ודגם שלא התקבל בזמן ריצה מוחזר לקודמו. Astra, Opus ומשפחות חדשות מופיעים כמועמדים לבדיקה
ידנית. בדף הראשי ובכלי MCP `model_watch_status` רואים את הדגם הפעיל ואת תוצאת הבדיקה;
`model_watch_check` מפעיל בדיקה מיידית. משימות חדשות מציגות הסבר בעברית; דף Deliver מציג
גם את אופן המימוש הנוכחי על פי סוג ההרצה, מיקום המימוש, מצב המשימה והמאזינים.

### למה `baseline`
תוכנית המשחק (`context/`, `docs/game/`, `game/`, `schemas/game`, `AGENTS.md`, `skills/`) **אינה במעקב git** כרגע, ולכן worktree שנוצר מ־HEAD לא היה מכיל אותה. `baseline` מצלם את הנתיבים האלה לענף נפרד `wwii-build/integration` דרך **index זמני** (`read-tree HEAD` → `add` → `write-tree` → `commit-tree` → `update-ref` בתנאי create-only). הענף, ה־index וה־working tree שלך לא נגעים — הפקודה מוודאת ש־`git status` זהה לפני ואחרי. כל משימה מתפצלת מענף האינטגרציה, ועבודה שעברה קבלה ממוזגת רק אליו. מתי למזג את `wwii-build/integration` לענף שלך — החלטה שלך.

## איך מזוהה אימות ה־CLI (ולמה לא ייווצר חיוב API בשקט)

| | בדיקה (ללא inference) | מצב מותר | חסימה |
|---|---|---|---|
| Codex | `codex login status` | `Logged in using ChatGPT` (מנוי) | API key → `BILLING_BLOCKED` אלא אם `billing.allow_api_billing = true` |
| Claude | `claude auth status --json` | `authMethod` ברשימת `subscription_auth_methods` | API key / Bedrock / Vertex / ערך לא מוכר → חסום |

הגנות נוספות:
- ה־workers מקבלים **סביבה מ־allowlist** בלבד: `ANTHROPIC_*`, `OPENAI_*`, `CLAUDE_CODE_*` ומשתני session של אפליקציית הדסקטופ לא עוברים לעולם.
- Claude: אירוע `rate_limit_event` עם `isUsingOverage` (שימוש נוסף בתשלום) **עוצר את הריצה מיד** וחוסם את המשפחה עד ה־reset, אלא אם `billing.allow_claude_overage = true`. אין שימוש ב־`--bare` (הוא מעביר את האימות ל־API key בלבד).
- Codex: המודל וה־effort **תמיד** נשלחים במפורש, ו־`--ignore-user-config` מונע ירושה של ברירת המחדל ב־`~/.codex/config.toml` (אצלך כרגע `gpt-6-astra`/`ultra`).
- קריאת המכסה של Codex עוברת דרך `codex app-server` עם **allowlist קשיח של מתודות** (`initialize`, `account/rateLimits/read`, `account/read`). `account/rateLimitResetCredit/consume` (צריכת reset שמור) ו־`sendAddCreditsNudgeEmail` לא יכולות להישלח.
- המערכת לא קונה, לא מפעילה reset בתשלום, לא צורכת reset שמור ולא מפעילה API billing. כשנגמרת מכסה: fallback, המתנה, או שאלה אליך.

Claude Code מותקן כרגע רק בתוך אפליקציית Claude לדסקטופ; המנהל מאתר אותו אוטומטית (PATH → `~/.claude/local` → חבילת האפליקציה), או לפי `providers.claude.command`. כדי להשתמש בו כ־worker צריך להתחבר פעם אחת בטרמינל: `claude auth login` (עם המנוי). המנהל לא משתמש ב־session של אפליקציית הדסקטופ.

## start / pause / resume / stop / kill

```bash
wwii-build start                       # Ctrl-C = stop חינני; Ctrl-C שני = kill
wwii-build pause                       # לא מתחילות משימות חדשות; רצות מסיימות
wwii-build pause --interrupt-running   # גם עוצר רצות (SIGINT); העבודה נשמרת ב־worktree → PAUSED
wwii-build resume                      # ממשיך; PAUSED → PENDING
wwii-build stop                        # מונע התחלות, SIGINT לכל worker, המתנה (20s), SIGTERM, SIGKILL; שומר state
wwii-build kill                        # חירום: SIGKILL מיידי, מסמן emergency-stop; resume --clear-emergency כדי לחזור
wwii-build status | tasks | task <id> | approvals | events -n 100
wwii-build approve <approval-id|task-id> [--model astra]    wwii-build reject <id> --note "..."
wwii-build retry <id> | skip <id> [--as-satisfied] | recheck <id> [--run] | set-provider <id> <model-key>
wwii-build providers | provider refresh|reset-done codex|claude
wwii-build worktree list | prune       # prune מסיר רק worktrees נקיים של משימות PASSED; הענף נשאר
wwii-build jev status | docs-refresh   # מצב Jev/cache; refresh קורא תיעוד חי במפורש
wwii-build listener status             # Episode/Build State ו-listeners שנבחרו
```

## אפליקציה חיה: ארכיטקטורת socket

### ארכיטקטורה

```
דפדפן (static/app, ES modules) <── /ws (WebSocket, RFC 6455, stdlib) ──> תהליך ה־dashboard ──> SQLite (WAL)
                                                                           │  wwii_build/ws.py    Hub: handshake, framing, hello, ping
                                                                           │  wwii_build/live.py  LiveState: topics, snapshot/patch, actions
                                                                           └─ חוט "dashboard-live": PRAGMA data_version כל 0.25s
scheduler daemon · CLI · MCP server  ──────────── כותבים ל־SQLite כמו קודם (לא השתנו)
```

- המצב נשאר ב־`.wwii-build/state.sqlite3` ונכתב גם מתהליכים אחרים (ה־scheduler, ה־CLI, שרת ה־MCP). אף אחד מהם לא יודע על ה־socket.
- זיהוי שינוי: חיבור SQLite ייעודי בתוך תהליך ה־dashboard קורא `PRAGMA data_version` (הערך משתנה בכל commit של חיבור **אחר**). בשינוי, כל נושא שיש לו מנוי מחושב מחדש מאותן שאילתות שמשרתות את ה־HTTP, מושווה למה שנשלח לאחרונה, ורק ההפרש נשלח (`patch`) למנויי אותו נושא. גם כתיבה של פעולה מה־socket נתפסת כך (חיבור הכתיבה שונה מחיבור הזיהוי); שיחת המצב מעירה את החוט מיד ב־`poke()`. נושאים בלי מנויים נמחקים מהזיכרון. מצב ה־daemon אינו כתיבה למסד, ולכן `overview` מחושב מחדש גם כל 2 שניות.
- אין polling בדפדפן ואין רענון דף: הלקוח מחזיק חיבור אחד, נרשם לנושאים של הדף שמוצג ומעדכן את ה־DOM מה־`patch`. הדפים הקלאסיים תחת `/classic/` סטטיים לחלוטין.
- פעולות הן אותו קוד כמו טפסי ה־HTML: `Dashboard.action()` (דרך `run_form`) ב־worker thread, ורק העלאות קבצים נשארות POST מסוג multipart ב־HTTP.

### פרוטוקול ההודעות

כל הודעה היא אובייקט JSON אחד בפריים טקסט. שדה `type` קובע את סוג ההודעה; סוג לא מוכר מחזיר `{"type":"error","error":"unknown_type",...}`.

| כיוון | `type` | דוגמה |
|---|---|---|
| לקוח → שרת | `hello` | `{"type":"hello","token":"<token>"}` — חייבת להיות ההודעה הראשונה; השרת עונה `{"type":"welcome","server_time":"2026-01-01T00:00:00+00:00"}` |
| לקוח → שרת | `subscribe` | `{"type":"subscribe","topics":["overview","task:A/1"],"revs":{"overview":1767225600123}}` |
| שרת → לקוח | `snapshot` | `{"type":"snapshot","topic":"approvals","rev":1767225600123,"data":{"key":"id","items":[{"id":7,"kind":"model"}],"meta":{}}}` |
| שרת → לקוח | `patch` | `{"type":"patch","topic":"approvals","rev":1767225600124,"upsert":[{"id":8,"kind":"model"}],"remove":[7],"meta":{...}}` (`meta` רק כשהשתנה) |
| שרת → לקוח | `event` | אין סוג הודעה נפרד: שורות חדשות ביומן מגיעות כ־`patch` של הנושא `events` — `{"type":"patch","topic":"events","rev":…,"upsert":[{"id":412,"event":"AUTO_APPROVAL_MODE_CHANGED","detail":{…}}],"remove":[]}` (רק שורות חדשות, לפי סדר `id`; פרצה של יותר מ־200 שורות נשלחת כ־`snapshot`) |
| שרת → לקוח | `subscribed` | `{"type":"subscribed","topics":["overview"],"current":[],"rejected":["nope"]}` — אישור לכל `subscribe`; `current` = נושאים שה־`rev` של הלקוח כבר עדכני בהם (לא נשלח להם snapshot) |
| לקוח → שרת | `unsubscribe` | `{"type":"unsubscribe","topics":["task:A/1"]}` |
| לקוח → שרת | `action` | `{"type":"action","id":"req-1","name":"set_auto_approve_all","args":{"enabled":true}}` — `name` הוא שדה ה־`action` של הטופס הקלאסי; `args` הם שדות הטופס (בוליאני → `"1"`/`"0"`, `null` → `""`, רשימה → שורה לכל ערך, או פסיקים בשדות `mcp_servers` ו־`tool_names`) |
| שרת → לקוח | `action.result` | `{"type":"action.result","id":"req-1","ok":true,"message":"…"}` — הודעה אחת בדיוק לכל `action` (עד 2000 תווים) |
| שרת → לקוח | `progress` | `{"type":"progress","id":"req-1","line":"ממצא: …"}` — שורות מפעולה ארוכה (`unstick`, ‏`system_onboard`, ‏`state_chat`, ‏`graph_console_query`), תמיד לפני ה־`action.result` שלה; עד 500 שורות לפעולה |
| לקוח → שרת | `ping` | `{"type":"ping"}` ← השרת עונה `{"type":"pong"}` (בנוסף ל־ping/pong של פריימי WebSocket, שגם הם נענים) |

כללי עקביות: `rev` של נושא עולה ב־1 בכל שינוי ומתחיל מזמן היצירה באלפיות שנייה, כך ש־`rev` מריצה קודמת תמיד קטן מהנוכחי וגורר snapshot. לקוח שרואה פער ב־`rev` שולח שוב `subscribe` עם ה־`revs` שלו. `data.key` הוא שם השדה המזהה של כל פריט (`null` בנושאים הסינגלטוניים `overview` ו־`unstick`, שכל המידע שלהם ב־`meta`). שגיאת הודעה מחזירה `{"type":"error","error":"…","message_he":"…"}` בלי לסגור את החיבור.

### הנושאים (topics)

| נושא | מפתח פריט | תוכן |
|---|---|---|
| `overview` | — | `meta`: סטטוס, daemon, pause/emergency, ספירת משימות לפי מצב, גל, מודלים |
| `tasks` | `task_id` | כל המשימות (כולל `description_he`) |
| `workers` | `attempt_id` | ניסיונות פעילים |
| `quota` | `provider` | מצב מכסה לכל ספק |
| `approvals` | `id` | אישורים ממתינים |
| `events` | `id` | יומן האירועים (snapshot של 100 אחרונים, אחר כך שורות חדשות בלבד) |
| `delivers` | `deliver_id` | מרכז ה־Delivers: פריטים, קשתות, listeners, runtime, Jev |
| `unstick` | — | הדוח האחרון של "למה תקוע" |
| `rag` | `id` | מצב גרף ה־RAG ותוצאות הקונסולה |
| `plan` | `task_id` | הצעות המתכנן והמודלים |
| `subtasks` | `pattern_hash` | תתי־משימות ודפוסים |
| `deliver:<id>` | `capability_id` | דף Deliver אחד |
| `task:<id>` | `id` | דף משימה אחת (פירוט, ניסיונות, תלויות) |
| `chat:<n>` | `id` | הודעות שיחת המצב מספר `n` |

מזהים בנושאי `deliver:`/`task:` חייבים להתאים ל־`[A-Za-z0-9._:/@-]{1,200}`; נושא שאינו מוכר מוחזר ב־`rejected`.

### אבטחה

- **Host:** ה־dashboard מאזין על `127.0.0.1` בלבד, וכל בקשה — כולל שדרוג ל־`/ws` ו־`/app/…` — נבדקת מול `Host` של `localhost`/`127.0.0.1`/`[::1]` (הגנה מ־DNS rebinding); אחרת 403.
- **Origin מדויק:** בשדרוג ה־socket חייב להיות `Origin` בדיוק `http://127.0.0.1:<port>` או `http://localhost:<port>` (סכמה, מארח ופורט). חסר, שונה או `https` ← 403 לפני ה־upgrade.
- **טוקן ב־hello:** הטוקן (CSRF) נוצר בכל הפעלת תהליך ומוזרק רק ל־`index.html` של האפליקציה בזמן ההגשה; הוא אינו ב־URL ולא בקבצי ה־static. ההודעה הראשונה חייבת להיות `hello` עם הטוקן (השוואה ב־`secrets.compare_digest`) תוך 10 שניות, אחרת החיבור נסגר בקוד `4401`. הטוקן מאומת פעם אחת לחיבור ולכן אינו חלק מ־`args` של פעולה. טפסי ה־HTML ממשיכים לדרוש `token` בכל POST.
- **מגבלות גודל וקצב:** הודעה (אחרי הרכבת fragments) עד 1 MiB — חריגה נסגרת ב־`1009` כבר לפי האורך המוצהר, לפני קריאת הגוף; פריימים בינאריים ← `1003`, UTF-8 או JSON שאינו אובייקט ← `1007`, פריים לקוח ללא mask ← `1002`; עד 30 פריימים לשנייה לחיבור (חריגה ← `4429`); עד 64 נושאים לחיבור; עד 8 פעולות במקביל לחיבור (מעבר לכך `ok=false`); שם פעולה חייב להתאים ל־`[a-z][a-z0-9_]{0,63}`.
- **כיבוי:** `Dashboard.shutdown()` סוגר כל socket ב־`1001`, ממתין שנייה ואז מנתק בכוח.

### איך מוסיפים נושא (topic) חדש

1. ב־`wwii_build/live.py`: להוסיף את השם ל־`STATIC_TOPICS` (או ל־`ARG_TOPICS` לנושא עם פרמטר), את שדה המפתח ל־`KEYS` (או `None`), ואם החישוב כבד — גם ל־`HEAVY`.
2. ב־`LiveState._build(kind, arg, sweep)`: להחזיר `(items, meta)` מאותן שאילתות שדף ה־HTTP משתמש בהן (עדיף פונקציה ב־`app_data.py`, ללא קוד שחוזר). פריטים חייבים להיות JSON־serializable ובעלי שדה המפתח. אם יש fingerprint זול — להחזיר אותו מ־`_fingerprint`.
3. אין צורך לכתוב קוד זיהוי שינוי: ה־diff וה־`rev` נעשים אוטומטית. אם הנושא תלוי במשהו שאינו כתיבה ל־SQLite (כמו מצב ה־daemon), יש לסמן אותו `dirty` מחזורית, כפי ש־`tick` עושה ל־`overview`.
4. בדיקה ב־`tests/test_ws_live.py` (כתיבה מחיבור שני ← `patch`, וה־snapshot הראשון).

### איך מוסיפים דף חדש

1. ליצור `wwii_build/static/app/pages/<name>.js` שמייצא `mount(ctx)` ומחזיר פונקציית ניקוי. `ctx` כולל `store` (הרשמה לנושאים דרך `makeWatcher(store)` מ־`widgets.js`), `root`, `params` מה־hash, ‏`act` (שליחת פעולה), ‏`upload`, ‏`fetchJson` ו־`toast`. בונים DOM ב־`h()`/`setChildren()` מ־`dom.js` (בלי `innerHTML` וללא `location.reload`/`location.href` — נבדק ב־`test_app_shell.py`), ופעולות שולחים דרך `ctx.act` (או `forms.js`/`operations.js`).
2. ב־`router.js`: להוסיף שורה ל־`PAGES` (`name: () => import('./pages/<name>.js')`) ואם צריך כניסה בניווט — ל־`NAV`.
3. אם הדף צריך נושא חדש — ראו הסעיף הקודם. טקסט ממשק בעברית, ו־RTL כבר מוגדר ב־`index.html`.
4. בדיקות: טסט צד־לקוח ב־`tests/js/*.test.mjs` (רץ מתוך `test_app_shell.py` כשיש node), וטסט צד־שרת לנושא. הקבצים מוגשים אוטומטית תחת `/app/<file>`; `test_every_module_the_app_imports_is_served` מוודא שכל import מוגש.

בדיקת קצה־לקצה של כל השרשרת (dashboard אמיתי ← socket ← כתיבה מחיבור שני ← פעולה) נמצאת ב־`tests/test_e2e_live.py`.

## יומן אירועים

טבלת SQLite בשם `event_log` בתוך `.wwii-build/state.sqlite3` היא מקור האמת של יומן האירועים. כל כתיבה עוברת דרך `DB.event`, שמסירה מידע רגיש לפני השמירה ומחזירה מזהה רשומה קבוע. הדשבורד ב־`/events`, ‏JSON API ב־`/api/events`, פקודת `wwii-build events` וכלי MCP בשם `event_log_list` ו־`event_log_get` קוראים כולם דרך אותו journal שמור. הדף מאפשר חיפוש, סינון לפי סוג אירוע, ספק ומשימה, ודפדוף לאירועים ישנים יותר.

## Jev, קונטקסט ו־Deliver listeners

כל קונטקסט שנשלח ל־LLM עובר דרך Jev במצב fail-closed. החיפוש הדטרמיניסטי והגרף מייצרים shortlist בלבד; Jev בוחר חבילות קונטקסט, כולל חבילת הבסיס הנדרשת. Jev כבוי, שגיאה או `no_match` אינם מפעילים worker. פונקציות דטרמיניסטיות ממשיכות לפעול בלי LLM.

החיבור הוא ישירות לשירות TypeSafe החיצוני דרך `typesafe-sdk==0.7.2`, ‏`TypeSafeClient` ו־`Choice`; אין שירות Jev מקומי. שם משתנה הסביבה הרשמי הוא `TYPESAFE_API_KEY`. לחלופין, בעמוד `/delivers` אפשר להזין את המפתח בשדה סיסמה. הוא נשמר ב־macOS Keychain בלבד, נמסר ל־SDK בזיכרון, ולעולם אינו נכתב ל־SQLite, לקונפיג, ל־URL, ללוג או לריפו. שמירה מפעילה מיד model listing ובקשת Choice קטנה מול 2–3 Deliver IDs קיימים. הסטטוסים הם `READY`, `MISSING_CREDENTIAL`, `AUTH_FAILED`, `API_UNREACHABLE`, `RATE_LIMITED`, `NO_CREDITS` ו־`INVALID_RESPONSE`.

כל Deliver מתאר את ה־listeners שהוא מציע ב־`docs/game/DELIVER_LISTENER_CATALOG.json`. רק ההצעות של ה־Deliver שפלט את האירוע נבדקות, selector דטרמיניסטי מסנן אותן לפי `EpisodeState` ו־`BuildState`, ו־Jev חייב לבחור כל activation במפורש. הפירוט והדוגמה המלאה של שלג נמצאים ב־`docs/game/JEV_LISTENER_RUNTIME.md`; התצוגה הגרפית נמצאת ב־`/delivers` בדשבורד.

עמוד `/delivers` הוא גם ממשק השליטה: מוסיפים ועורכים Delivers, context candidates, מחירים ותקציבים. לחיצה על Deliver פותחת דף עם ההגדרה, המודל, dependencies, listeners, provenance, היסטוריית ניסיונות וקישורים ל־artifacts ולמסך “מה נבנה”. בראש כל מסך יש prompt בשלושה מצבים: תכנון ובנייה, המלצה מה לעשות עכשיו ושאילתת גרף. חיפוש הגרף הוא דטרמיניסטי, וכל תוצאה שמוכנסת לפרומפט נבחרת קודם ב־Jev. ה־planner מתבקש להשלים גם חוזים, תלויות, listeners, בדיקות ו־context שחסרים בבקשה החלקית.

קונסולת השאילתות ב־`/rag` פועלת מיד ואינה יוצרת משימה בתור. שאילתת Cypher, שאלה חופשית למודל המקומי ושאלה חופשית ל־Codex או Claude מחזירות תוצאה באותה בקשה. במסלול LLM רק מקטעי evidence שבחר Jev נכנסים לפרומפט, והתוצאה שומרת ספק, זמן, usage ומזהי מקורות. בחירת מודל חיצוני אינה יוצרת משימת `PLAN` סמויה.

לתיבת המתכנן אפשר לגרור עד שמונה תמונות או קבצים ולתאר באותו prompt מה לעשות לפיהם. הקבצים נשמרים תחת `.wwii-build/planner_uploads/` ולא בריפו. Jev מקבל metadata ותקציר קצר בלבד ובוחר אילו קבצים דרושים; רק הנבחרים נכנסים לקונטקסט. Codex מקבל תמונות נבחרות דרך `--image`, ו־Claude מקבל הרשאת קריאה רק לתיקיית ה־hash המבודדת של כל קובץ שנבחר. כלי MCP `planner_request` תומך באותו מסלול דרך `attachments` מקודדים ב־base64.

בזמן ריצה, `/delivers` מציג מדדים שמחושבים ישירות מ־SQLite: גודל שכבת הקונטקסט הרשומה, מספר וגודל חבילות הקונטקסט שנבנו, קונטקסט של workers פעילים, זיכרון טוקנים מצטבר, שימוש Jev שנשמר ועלות worker מדווחת. עלות חסרה נשארת מסומנת כלא ידועה ואינה נספרת כאפס. כל כרטיס ודף Deliver מציגים גם את נפח הקונטקסט השייך אליו. activations במצב `SELECTED` או `RUNNING` מוצגים כ־listeners פעילים עם המקור, היעד והאירוע שגרם להפעלה.

Delivers דטרמיניסטיים נשמרים באותו קטלוג ומוצגים במדף קומפקטי נפרד. דף הפרטים שלהם כולל חוזה פונקציה, קונטקסט, listeners, היסטוריית אירועים והרצות שמורות, בלי בחירת מודל או תמחור LLM. כלי MCP בשם `deterministic_run_record` שומר התחלה, סיום, נפחי קלט/פלט ופרטים תפעוליים בעלות מודל קבועה של אפס. כלי `listener_activation_update` מעדכן activation קיים בין `SELECTED`, ‏`RUNNING` ומצבי הסיום החוקיים, כדי שהתצוגה החיה תשקף את מה שרץ בפועל.

אותן פעולות זמינות כשרת MCP בשם `wwii_task_manager` דרך `.mcp.json` ו־`tools/build_manager/bin/wwii-build-mcp`. כלי `jev_selected_graph_query` מחזיר למודל רק evidence שנבחר במפורש ב־Jev; כלי הכתיבה משתמשים באותו action path כמו הדשבורד. בנוסף קיימים `task_model_set`, ‏`deliver_model_set`, ‏`task_dependency_add`, ‏`task_context_access`, ‏`task_expedite`, ‏`scoped_change_request`, ‏`deterministic_run_record` ו־`listener_activation_update`, כך שבחירת מודל למשימה או ל־Deliver, תלות, הרשאת קונטקסט, הקדמה חד־פעמית של משימת `READY`, פרומפט ממוקד ומצב ריצה זמינים גם מה־MCP. כלי `subtask_create`, ‏`subtask_patterns` ו־`subtask_promote` שומרים פירוק למשימות עם מודל/קונטקסט/כלים משלהן, מציגים שימוש חוזר ומאפשרים קידום מפורש בלבד. כלי `rag_graph_status`, ‏`rag_graph_query`, ‏`rag_graph_configure` ו־`deliver_graph_access_set` מחברים את גרף ה־RAG הקיים, מציגים את מצבו ומנהלים הרשאת `none`/`limited`/`full` לכל Deliver. מתכנן המשימות מקבל גישה מלאה; בכל המסלולים התוכן שנשלף נשאר מועמד עד לבחירה מפורשת של Jev. המפתח של TypeSafe אינו כלי MCP ואינו נחשף בו.

שירות הגרף הוא ה־API הציבורי לקריאה בלבד של אטלס מלחמת העולם השנייה (מאגר `wwii-atlas`, תיקיית `api/`). אין כתובת ברירת מחדל; מגדירים אותה ב־`[graph_rag].url` או במסך **גרף RAG**. רק כתובות HTTPS ציבוריות מתקבלות — כתובות מקומיות ופרטיות נחסמות. קונסולת ה־Cypher דורשת את `WW2_GRAPH_CONSOLE_KEY` בסביבה.

אותן פעולות ב־dashboard: PAUSE / STOP (עם אישור אחד), Advanced → Pause+interrupt ו־Emergency kill, ובכל משימה Approve / Reject / Skip / Retry / Change provider / Re-run acceptance.

כל worker רץ בתהליך נפרד בקבוצת תהליכים משלו, עטוף ב־`childguard`: אם ה־daemon מת (crash, SIGKILL, סגירת טרמינל), ה־guard שולח SIGINT ואז SIGKILL ל־CLI. לא נשארים תהליכי Claude/Codex יתומים (נבדק בטסט שמבצע SIGKILL ל־daemon).

**Restart:** בהפעלה הבאה `reconcile` בודק תהליכים ששרדו (PID + זמן התחלה, כדי לא לפגוע ב־PID ממוחזר), מבצע commit לעבודה שלא נשמרה ב־worktree, מחזיר משימות RUNNING ל־PENDING ומשימות CODE_READY לקבלה חוזרת (בלי להריץ שוב את המודל). משימה PASSED לעולם לא רצה שוב. קבלה נשמרת כ־receipt שקשור ל־commit; אם ה־HEAD לא השתנה לא מריצים שוב.

**שינה של ה־Mac:** אין הנחה של daemon 24/7. כל הטיימרים הם זמנים אבסולוטיים ב־SQLite; פער בין שעון הקיר למונוטוני מזוהה כ־`WAKE_FROM_SLEEP`, והלולאה מחשבת מחדש מצב, resets ו־backoff.

## מכסות (QuotaManager)

מצב נשמר לכל `provider / account / family`: `AVAILABLE, NEAR_LIMIT, BLOCKED_SESSION, BLOCKED_WEEKLY, BLOCKED_UNKNOWN, AUTH_ERROR, BILLING_BLOCKED, MODEL_UNAVAILABLE, MISSING, UNKNOWN`, עם `blocked_until`, `session_reset_at`, `weekly_reset_at`, `used_percent`, `confidence` ו־`source`.

- **Codex:** נקרא machine-readable ללא inference (`account/rateLimits/read`): אחוז שימוש, חלון (דקות) ו־`resetsAt`. נקרא בהפעלה, אחרי כל ריצה, כשזמן reset ידוע עבר, וב־`provider refresh`. לא ב־polling.
- **Claude:** ל־CLI אין קריאת מכסה בלי inference, ולכן המצב הוא `UNKNOWN` עד שמגיע מידע מריצה (`rate_limit_event`: `five_hour` / `seven_day` / `seven_day_opus` / `seven_day_sonnet`, `resetsAt`). **אין אחוז מומצא**; ה־dashboard כותב `unknown`.
- הגעה למגבלה **אינה FAILED**. הניסיון נרשם `QUOTA_LIMITED`, המשימה חוזרת לניתוב, והמגבלה חוסמת רק את התחום שצוין (למשל Opus שבועי חוסם Opus בלבד; Sonnet ממשיך).
- reset ידוע: חסום עד reset + מרווח (120s). reset לא ידוע: backoff חסום (15m → 30m → 60m → 120m), בלי busy loop. `wwii-build provider refresh <p>` מאפשר בדיקה ידנית.
- מגבלה שנצפתה בריצה אמיתית גוברת על snapshot סותר עד זמן ה־reset שלה (מונע flapping).
- ה־scheduler מחשב `next_wakeup_at` מה־reset הרלוונטי המוקדם ביותר ומזמני backoff, וישן עד אז (בדיקת פקודות מקומית כל 2s מול SQLite; אף פעם לא מול ספק).

## Fallback וניתוב

לכל `model_profile` מהרישום יש שרשרת ב־`[routing]` (נגזרה מ־`model_profiles` ברישום):

| פרופיל | שרשרת |
|---|---|
| IMPLEMENT / VISUAL | sol (Codex) → sonnet (Claude) |
| DESIGN | sonnet → sol |
| RESEARCH | opus → sonnet |
| DEEP | astra → opus — **שניהם באישור ידני** |
| EXTRACT | luna → haiku |
| REVIEW | opus → sol |

סדר העדיפות: בחירה ידנית (`set-provider`) → אותו מודל ב־retry (affinity) → השרשרת. fallback קורה **בין ניסיונות, לא באמצע ריצה**. כשכל המועמדים חסומים: `WAITING_QUOTA` עד ה־reset הקרוב. כשאין ספק שמיש (לא מחובר, מושבת, חסר): `WAITING_PROVIDER`.

**כבוי ספק:** `[providers.codex] enabled = false` (או claude). **כיבוי fallback:** `[fallback] enabled = false`.

**אישור למודלים יקרים:** `approvals.astra = "required"` (ברירת מחדל), `models.astra.automatic = false`. כדי לחייב אישור לכל Opus: `approvals.opus = "required"`. משימות DEEP דורשות אישור ידני כברירת מחדל (`deep.require_manual_approval`). דחייה מעבירה לשלב הבא בשרשרת. אישור נשמר למשימה בלבד.

## Retry ו־escalation

- כישלון טכני או כישלון בדיקות: retry על **אותו מודל**, עם קונטקסט retry בלבד (diff קודם, פלט הבדיקות שנכשלו, handoff קודם), בלי כל ההיסטוריה.
- אחרי `scheduler.escalation_threshold` (3) כישלונות: `BLOCKED` + בקשת `ESCALATION_REQUIRED`. אתה בוחר: לנסות שוב, מודל אחר (למשל astra), או לסמן FAILED.
- worker שמחזיר `status: blocked` יוצר המלצה `ASTRA_RECOMMENDED`. זו המלצה בלבד; שום דבר לא רץ בלי אישור.
- מכסה, auth, מודל לא זמין ו־interrupt אינם נספרים ככישלון.

## קונטקסט (ContextBuilder)

לכל ריצה: `INVARIANTS.md` + `DOMAIN.md` של התחום + כרטיס התפקיד בלבד + ה־BRIEF + רשומות הרישום של ה־lego ids של המשימה + handoffs של התלויות (ממשק/סיכום, לא מימוש) + evidence מה־overlay. מסמכי רקע של החבילה נשלחים **כהפניה** בלבד, וכרטיסי תפקיד ותחומים אחרים של אותה חבילה **מוחרגים במפורש**. כל ריצה נרשמת: פריטים, sha256, בתים, סיבה. ה־prompt המדויק נשמר ב־`.wwii-build/context_packs/<task>/a<attempt>/prompt.md`. כל משימה מתחילה session חדש ולא־מתמשך (`--ephemeral` / `--no-session-persistence`), ו־Claude רץ ב־`--safe-mode` (בלי CLAUDE.md, skills, hooks או MCP).

דוגמה (טסט): `B01/ground_platform` מקבל invariants + ground_vehicles + ground_platform + B01. `ground_powertrain.md` מוחרג, ואין שום קובץ naval או aviation.

## קבלה דטרמיניסטית

אחרי כל worker המנהל מריץ בעצמו:
- **בדיקות מובנות:** ownership (כל קובץ ששונה בתוך ה־write scope), `git diff --check`, סריקת סודות, שינוי לא ריק, תקינות handoff, ומדיניות שינויי תלויות.
- **פקודות:** `[acceptance].default_commands` (ברירת מחדל: 47 בדיקות החוזים הקיימות ב־`game/tests`), פקודות המשימה מ־`plan_overlay.toml`, ו־pytest על קבצי טסט שה־worker הוסיף בתוך ה־scope שלו.

אם אין פקודה ייעודית למשימה, ברירת המחדל היא `REVIEW_REQUIRED` (`review.auto_pass_requires_task_commands`). במסך **משימה חדשה** אפשר לבחור אישור אוטומטי למשימה אחת, או להפעיל **אישור אוטומטי להכול**. המצב הגלובלי נשמר ב־SQLite, מאשר מיד גם שערי review שכבר ממתינים, וחל על משימות עתידיות עד שמכבים אותו. בשני המצבים המשימה עדיין חייבת לעבור את בדיקות הבעלות, ה־diff, הסודות, פקודות ברירת המחדל וכל פקודת קבלה שהוגדרה; כשל אינו מאושר אוטומטית. אפשר לשלוט במצב גם דרך MCP `auto_approval_mode` או ליצור משימה עם CLI `wwii-build add-task ... --auto-approve`.

## תיקון אוטומטי (Repair Tasks) במקום הרצה מחדש

כש־worker סיים אבל הקבלה נכשלה, המנהל **לא** שולח את כל המשימה שוב למודל גדול. הוא מסווג את הכישלון (`repair.py`):

| סיווג | מה קורה |
|---|---|
| `GENERATED_ARTIFACT_FALSE_POSITIVE` | `__pycache__`, `*.pyc` ודומיהם מוסרים דטרמיניסטית ו־acceptance רץ שוב, בלי LLM |
| `REPAIRABLE_CODE` (בדיקה/‏build/‏lint/‏diff-check) | נוצרת `REPAIR/<task>/<n>` |
| `SCOPE_ERROR` (קובץ אמיתי מחוץ ל־scope) | repair שמחזיר או מזיז את השינוי; שינוי בקבצים של בעלים אחר נרשם כבקשה בין־תחומית |
| `REPAIRABLE_HANDOFF` (handoff לא תקין) | repair לקריאה בלבד שמחזיר רק JSON |
| `DEPENDENCY_MISSING` (import ממודול של משימה שטרם עברה) | ההורה עובר ל־`BLOCKED` ונרשמת בקשה בין־תחומית; **אין repair** ולא ממציאים את התלות |
| `ARCHITECTURAL_CONFLICT` (נגיעה בחוזה משותף) | ההורה עובר ל־`ARCHITECTURE_REVIEW_REQUIRED`; אתה מאשר ובוחר מודל |
| `NO_OUTPUT` | אין מה לתקן, ולכן ניסיון רגיל של המשימה |
| מכסה, auth, ספק | **אינם** repair; מטופלים ברמת הריצה (fallback או המתנה) |

- **מצבים חדשים:** ההורה ב־`WAITING_REPAIR` וה־repair עובר מחזור רגיל (READY → RUNNING → PASSED/FAILED). בנוסף יש `ARCHITECTURE_REVIEW_REQUIRED`.
- **worktree ונעילה:** ה־repair עובד ב־**worktree של ההורה** על אותו diff. נעילת הכותב של ההורה נשארת מוחזקת, ורק ה־repair הפעיל שלו רשאי לכתוב.
- **קונטקסט מינימלי:** invariants, כרטיס התפקיד, הכישלון המדויק ופלט הבדיקות, ה־diff הנוכחי, ה־handoff הקודם, קבצים שהוזכרו בכשל, הפקודות, והיסטוריית repairs קודמים (מ־#2 והלאה). ה־BRIEF, ה־DOMAIN והרישום **מוחרגים**.
- **ניתוב זול:** `REPAIR_CODE` הוא Codex Sol; ראיות היסטוריות עוברות ל־Sonnet. Opus/Astra ב־repair תמיד דורשים אישור, ואף פעם לא "יורשים" את המודל של ההורה.
- **תקציב:** עד 3 repairs למשימה. #3 משתמש בשרשרת `REPAIR_ESCALATED`. אחר כך ההורה עובר ל־`BLOCKED` עם `REPAIR_LIMIT_REACHED`, ואתה מאשר repair נוסף (אפשר על מודל אחר) או דוחה.
- **מי מחליט:** אחרי כל repair **המנהל** מריץ את הקבלה של ההורה. המודל לא קובע אם ההורה עבר.
- **אין עצירה גלובלית:** כישלון במשימה לא עוצר את כל ה־build. רק התלויים בה ממתינים, ושאר העבודה ממשיכה.
- **בדיקה חוזרת בלי LLM:** `wwii-build recheck <task> --run` מריץ קבלה על ה־worktree הקיים כשה־daemon לא רץ.

## "עשיתי reset במכסה" (Claude / Codex)

אם השתמשת ב־reset של מכסה בתוך אפליקציית Claude או Codex, לחץ ב־dashboard על **"I did a … usage reset in the app"** או הרץ `wwii-build provider reset-done codex|claude`. המנהל מנקה את חסימת המכסה של הספק, מחזיר משימות מ־`WAITING_QUOTA` לתור, ועבור Codex קורא מיד את המכסה האמיתית (אם ה־reset לא נקלט, החסימה חוזרת לפי הנתון האמיתי). המנהל עצמו לעולם לא מבצע reset, לא צורך reset שמור ולא קונה.

## משימה ידנית, פרומפט ← משימות, MCP, עברית

**משימה ידנית:** דף "+ New task" ב־dashboard, או `wwii-build add-task "כותרת" --scope hud/ --model sonnet --dep B01/ground_platform --context notes/x.md --mcp ww2_atlas --check "pytest hud"`.
- **אפשרויות:** מודל (אפשר לבטל fallback כדי לנעול את המודל), בעלים, תלויות, תחום כתיבה או קריאה בלבד, קובצי קונטקסט שנכנסים לפרומפט (גם קבצים שקיימים רק בעותק העבודה שלך), נתיבי עיון, שרתי MCP, חוזה כלים ייעודי, פקודות קבלה ואישור אוטומטי אחרי בדיקות מוצלחות.
- **בדיקה לפני יצירה:** האימות דטרמיניסטי. תלות שלא קיימת, מודל לא ידוע, נתיב מוחלט או עם `..`, ושרת MCP שאינו מוגדר לספק של המודל נדחים. חפיפה לתחום של משימה אחרת מוצגת כאזהרה.
- **בחירת המודל היא האישור:** גם Opus או Astra ירוצו בלי לשאול שוב.
- **קדימות אוטומטית:** משימה שנוצרה ישירות בידי המשתמש וללא תלויות מקבלת קדימות בתור. משימה עם תלויות נשארת בסדר הרגיל עד שהן הושלמו.

**בקשת קרב (שרשרת בונה הקרבות בפעולה אחת):** דף "בקשת קרב" (קלאסי: `/classic/battle`, ובאפליקציה החיה `#/battle`), `wwii-build battle-request "Brécourt Manor assault" --date 1944-06-06 --bbox=-1.3,49.3,-1.1,49.5`, או כלי MCP `battle_request`.
- **קלט:** כותרת, `battle_key` (slug; נוצר מהכותרת אם חסר), תאריך או טווח `YYYY-MM-DD..YYYY-MM-DD`, ואופציונלית מקום, `bbox` (מערב,דרום,מזרח,צפון) והערות. `--dry-run` מציג את השרשרת בלי ליצור.
- **פלט:** חמש משימות פרויקט דרך `manual.create_tasks`: תיק ראיות ← מחקר מפות (חובה) ← מחקר LLM ברשת עם חיפוש מונחה פערים ← שחזור ← חבילת אפיזודה. כל משימה מקבלת מודל לפי התאמה (פרופיל `fit` של השלב; מודל פרימיום או כזה שדורש אישור אינו ננעל אוטומטית), תחום כתיבה אחד תחת `game/episodes/<battle_key>/<שלב>/`, `description_he`, ופקודת קבלה ‏`tools/build_manager/battle_stage_check.py <שלב> <battle_key>` שבודקת את הקבצים שנוצרו (מבנה, provenance, ציטוטים, חיפוש לכל פער, גיבובי קלט בחבילה). `allow_web` פעיל רק במשימת המחקר.
- **המודולים הכלליים** (`game.battle_builder.*`) נבנים במשימות `MANUAL/bb-*`; משימות השרשרת קוראות להם ואינן משכתבות אותם. מודול שחסר גורם למשימה לעצור ולדווח על פער יכולת.
- **בקשה כפולה** לשרשרת שיש בה משימה שלא הסתיימה (`PASSED`/`FAILED`/`CANCELLED`) עבור אותו `battle_key` נדחית. אחרי שכולן הסתיימו אפשר לבקש שוב.
- **התבניות** נמצאות ב־`systems/battle_request_templates.toml` וניתנות לעריכה בלי שינוי קוד (הוראות, שלבים, תלויות, פרופיל מודל, פקודות קבלה). הקובץ אינו מניפסט של `onboard`.

**פרומפט ← משימות:** דף "Prompt → tasks", או `wwii-build plan "..."`.
- מודל זול (שרשרת `PLAN`: luna → haiku → sol) רץ לקריאה בלבד, רואה את המשימות הקיימות, הבעלים, המודלים, שרתי ה־MCP ואינדקס הקונטקסט, ומחזיר **הצעה** של משימות ותלויות.
- בקשת המתכנן עצמה מקבלת קדימות אוטומטית. הקדימות אינה עוקפת dependency, lock, quota או מגבלות מקביליות.
- המנהל מאמת את ההצעה (תלויות, מחזוריות, תחומים, מודלים, MCP). משימות נוצרות רק אחרי **Approve**, או מיד כאשר מתג האישור האוטומטי הגלובלי פעיל. הצעה לא תקינה אינה מוצעת לאישור.
- משימה עם `task_target=task_manager` היא תיקון מוגן למנהל עצמו. היא רצה ב־worktree מבודד שנזרע מצילום מדויק של הקוד הפעיל, מוגבלת ל־`tools/build_manager/`, ומחויבת ב־compile, בכל בדיקות המנהל ובבדיקת עליית CLI. לאחר הקבלה נבנית release שמורה, נבדק שלא היה drift בקבצים הפעילים, נשמר rollback, הקבצים מוחלפים אטומית והמנהל מבצע restart חינני. שינוי dependencies נחסם לבדיקה ידנית גם במצב אישור אוטומטי.

**תת־משימה אינה Deliver:** המתכנן או worker יכולים לפצל עבודה ל־Tasks שמורות. לכל Task יש מודל, קונטקסט, שרתי MCP, חוזה כלים, תחום כתיבה ובדיקות משלה. המופע נרשם יחד עם משימת האב. חוזה זהה שנוצר בפועל נספר כדפוס שימוש חוזר; הצעה שלא אושרה אינה נספרת. אחרי `subtasks.promotion_threshold` שימושים (ברירת מחדל: 3) הדפוס מסומן `eligible`, אך אינו מקודם אוטומטית. במסך `/subtasks` או דרך `subtask_promote` מקדמים אותו במפורש ל־Deliver, ואז נשמרים החוזה המלא וראיות המופעים ב־`deliver_templates`.
- המתכנן אף פעם לא כותב קבצים ולא מבצע commit.

**MCP:** ברירת המחדל נשארת "אין MCP" (Claude עם `--safe-mode --strict-mcp-config`; Codex עם `--ignore-user-config`). משימה שבחרה שרתים מקבלת רק אותם:
- **Claude:** `--mcp-config` זמני (הרשאות 0600, נמחק אחרי הריצה) ו־`--strict-mcp-config`, בלי הגדרות משתמש.
- **Codex:** קונפיג המשתמש נטען, וכל שרת אחר מקבל `enabled=false`.
- שרת שמוגדר עם הרשאת כתיבה (למשל `ww2_atlas` עם `ATLAS_MCP_ALLOW_WRITES=1`) מסומן באזהרה.

**עברית:** כל ממשק הניהול מוצג בעברית וב־RTL. מזהים, נתיבים, שמות מודלים ולוגים טכניים נשארים משמאל לימין כדי לשמור על דיוקם.

בכל משימה שכבר נמצאת ב־`READY` מופיע הכפתור **דחוף עכשיו**. הוא נותן לה קדימות חד־פעמית למחזור השיגור הבא ואז מתאפס; אפשר לבצע אותה פעולה דרך MCP `task_expedite`. הפעולה אינה מעבירה משימה חסומה ל־`READY` ואינה עוקפת תלויות, נעילות, מכסות או קיבולת.

**גרסת daemon:** משימות ידניות, מתכנן, העלאות, הקדימות החדשה ותיקון עצמי דורשים daemon בגרסת קוד 11 ומעלה. מול daemon ישן יותר היצירה נחסמת ומוצג באנר "restart required".

## ארטיפקטים שנוצרים אוטומטית
`generated.py` הוא מקום אחד למדיניות: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `.DS_Store`. הם לא נכנסים ל־commit, לא ל־diff, לא לבדיקת הבעלות ולא ל־artifacts. קבצים כאלה שכבר נכנסו לענף מוסרים מה־index לפני הקבלה. בדיקות הקבלה רצות עם `PYTHONDONTWRITEBYTECODE=1`, והכללים נוספים ל־`.git/info/exclude`. קבצים אחרים לא מוסתרים.

## איפה הכול נמצא

| מה | איפה |
|---|---|
| SQLite (מצב, ניסיונות, מכסות, אירועים) | `.wwii-build/state.sqlite3` |
| stdout/stderr/פקודה/receipt/diff לכל ניסיון | `.wwii-build/runs/<task>/a<id>/` |
| קונטקסט ו־prompt שנשלחו | `.wwii-build/context_packs/<task>/a<id>/` |
| artifacts (צילומים, וידאו, סצנות, 3D, דוחות) | `.wwii-build/artifacts/<task>/a<id>/` + ה־dashboard |
| קבצים ותמונות שנשלחו למתכנן | `.wwii-build/planner_uploads/<plan-task>/<sha256>/` |
| releases ו־rollback של תיקוני המנהל | `.wwii-build/system_releases/<system-task>/<commit>/` |
| פלט dry-run | `.wwii-build/dryrun/<timestamp>/` |
| worktrees | `.worktrees/<task>/` על ענף `wwii-build/task/<task>` |
| ענף אינטגרציה | `wwii-build/integration` |

`.wwii-build/` ו־`.worktrees/` מוחרגים דרך `.gitignore` וגם מקומית דרך `.git/info/exclude`. לוגים עוברים sanitization; אין tokens ב־SQLite.

## בדיקות

```bash
cd tools/build_manager/tests && python3 -m unittest discover -s . -p 'test_*.py'
```

כל הסוויטה (כולל `test_e2e_live.py` — dashboard אמיתי, socket וכתיבה מחיבור שני), בחינם: FakeCodexCLI / FakeClaudeCLI (`fakes/fake_cli.py`) מדברים באותם פורמטים כמו ה־CLIs המותקנים (JSONL של `codex exec --json`, JSON-RPC של app-server, ו־stream-json של Claude). הם מדמים הצלחה, rate limit עם reset, מגבלה שבועית, מודל לא זמין, פלט שבור, משימה ארוכה, SIGINT, crash, שגיאת auth, overage וכתיבה מחוץ ל־scope. `test_simulation.py` מריץ את תרחיש שלב 59 **על גרף ה־28 האמיתי** ואז את כל הגרף עד `B09/final_integration`.

smoke אמיתי (צורך מעט מכסת מנוי, ב־repo זמני בלבד):
```bash
python3 tools/build_manager/tests/smoke_real.py --provider codex --yes-spend-quota
```

## מבנה ועתיד Deliver

`wwii_build/models.py` מגדיר את החוזים היציבים: `TaskRequest`, `ContextPack`, `ExecutionQuote`, `ExecutionRun`, `Artifact`, `CapabilityGap`, `ReviewResult`. ה־scheduler מדבר רק עם `WorkerProvider` (`check_status`, `run_task`, `inspect_models`, interrupt/kill דרך ה־supervisor). `DeliverRuntimeProvider` עתידי יממש את אותו ממשק בלי לגעת ב־scheduler.

| מודול | תפקיד |
|---|---|
| `plan_importer.py` | גרף מהרישום + overlay |
| `scheduler.py` | לולאה, מצבים, one-writer, קבלה, אינטגרציה, reconcile |
| `routing.py` | בחירת מודל ו־fallback |
| `quota.py` | QuotaManager |
| `context_builder.py`, `prompts.py` | ContextPack, prompt קטן וסכמת ה־handoff |
| `providers/{codex,claude,limits}.py` | adapters ופרסור מגבלות |
| `supervisor.py`, `childguard.py` | תהליכים |
| `worktrees.py` | git worktrees, baseline, merge |
| `acceptance.py` | קבלה דטרמיניסטית |
| `dashboard.py` | ממשק |
| `control.py` | פקודות |
| `doctor.py`, `dryrun.py`, `cli.py` | CLI |

## מגבלות ידועות

- Claude: מצב המכסה `unknown` עד הריצה הראשונה (אין קריאה בלי inference). הטקסטים המדויקים של הודעות מגבלה ב־Codex/Claude עלולים להשתנות בין גרסאות; הודעה לא מזוהה נחשבת מגבלה בלי reset ידוע (backoff), ולא מנחשים זמן.
- `gpt-6-astra` לא מופיע ב־`codex debug models` המקומי. מצבו `UNKNOWN` עד ריצה מאושרת.
- worktree מלא (~90MB) לכל משימה. `[worktree] sparse = true` מקטין מאוד, אבל git יגדיר אז `extensions.worktreeConfig=true` בקונפיג הריפו.
- אין sandbox לקריאה: worker יכול לקרוא קבצים ב־worktree שלו מעבר לקונטקסט שנשלח. ההבטחה היא מה *נשלח* ומה *מותר לכתוב* (נבדק בקבלה), לא מה אפשר לקרוא.
- התראות macOS דרך `osascript`, מוגבלות בתדירות לכל מפתח.
