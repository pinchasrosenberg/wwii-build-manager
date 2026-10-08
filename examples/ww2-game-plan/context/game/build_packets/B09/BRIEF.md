# B09 — שילוב, שמירה וביקורת עצמאית

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-sol` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `IMPLEMENT`. בעלים: `runtime_continuity`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
פצל לשתי ריצות בבעלות runtime_continuity: B09/continuity_seam מתחיל אחרי B00/contracts ובונה snapshot/save/replay עם fixtures; B09/final_integration מחבר רכב, נשק, אנשים ומזג אוויר רק לאחר חבילות B01/B02/B04/B05/B06/B07/B08. בדיקות הרכיבים לפני השילוב משתמשות בחוזה snapshot וב־test double, ואינן ממתינות לשילוב הסופי. לאחר מכן בצע save/load אמיתי במהלך פעולה והזמן ביקורת עצמאית.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/simulation_runtime/DOMAIN.md`
- `context/game/domains/simulation_runtime/roles/runtime_continuity.md`
- `docs/game/IMPLEMENTATION_SEQUENCE.md`
- `docs/game/VALIDATION_REPORT.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `runtime.save`
- `runtime.replay`

## תוצרים
- שלב מוקדם: snapshot contract ו־fixture save/replay. שלב מאוחר: save/replay משולב על כל המודולים; אלה שתי TaskSlices ולא שתי חבילות נוספות.
- סצנה/מניפסט שילוב, save/replay, הוראות הרצה ותוצאות ביצועים על hardware מזוהה
- review נפרד: historical, provenance, simulation/integration, experience
- רשימת פערים למעבר M1→M2→M3; VR status לפי המכשיר שנבדק

## קבלה
- אין אובדן ID, ammo, fuel, casualty, relationship או variant בעת save
- שני דגמים ושתי תבניות נטענים באותו loader; שינוי קוד נדרש מנומק כיכולת כללית
- בדיקה אנושית של משחקיות; null לכל מדד שלא נמדד
- כותב המודול אינו מאשר לבדו את קבלתו

## כתיבה וגבולות
runtime_continuity לשמירה; תיקוני שילוב בבקשות לבעלי הקוד. reviewer מקבל read-only evidence/diff, לא write-all.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
