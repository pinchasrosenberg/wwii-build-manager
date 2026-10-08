# B00 — חוזים משותפים ו־host קטן

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-astra` / `high`. זמין בסביבה זו: `gpt-6-astra` / `high`.
פרופיל: `DEEP`. בעלים: `runtime_core`.
תלויות לפני מימוש: אין; חוזים/ראיות חסרים מתועדים כפער.

## הודעה להעברה לסוכן
הקפא את הממשקים הנדרשים לרכב, נשק, מזג אוויר ופעולת שחקן. ספק יחידות, גרסאות, semantics ו־fixtures; בנה host סינתטי headless קטן לאחר אישור התכנון הפנימי. חלק את הביצוע: תחילה B00/contracts; לאחר נתוני העיצוב B05/design, בצע B00/runtime_followup עבור actor_projection ו־battle_evaluator. השלמת העיצוב אינה ממתינה ל־evaluator.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/simulation_runtime/DOMAIN.md`
- `context/game/domains/simulation_runtime/roles/runtime_core.md`
- `game/contracts.py`
- `game/README.md`
- `docs/game/STACK_EVALUATION.md`
- `context/game/interfaces/README.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `runtime.ecs`
- `runtime.schedule`
- `runtime.physics_port`
- `runtime.events`
- `runtime.episode_loader`
- `runtime.actor_projection`
- `runtime.battle_evaluator`

## תוצרים
- ContractLock לחיבור ראשון, schemas/semantics ומיפוי לחוזי Python קיימים
- adapter typed GDScript עם boundaries ובדיקת loading/headless; בלי Rust/FFI כברירת מחדל
- רשימת migration ושדות חסרים; shared contracts בעריכה סריאלית
- TaskSlice המשך ל־runtime.actor_projection ול־runtime.battle_evaluator, בבעלות runtime_core, לאחר עיצוב B05; שומר ידע מורשה ומעריך תבניות נתוניות.

## קבלה
- שמות/יחידות/צירים/סדר tick/זמן/IDs מוגדרים; אין שני חוזים מתחרים לאותו מושג
- fixture רכב/נשק/סביבה עובר חיבור; גרסה לא תואמת נדחית
- תכנון Presentation/PlayerAction נפרד מליבת הסימולציה

## כתיבה וגבולות
game/contracts.py ו־schemas/game/contracts.schema.json רק בעדכון מתואם; תיקיית host עתידית תחת game/runtime/simulation_runtime/; אין שינוי בקוד Atlas/Deliver.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
