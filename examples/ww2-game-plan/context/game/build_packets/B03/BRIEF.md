# B03 — מחקר דגם וראיות היסטוריות

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `claude-opus-5-5` / `high`. זמין בסביבה זו: `gpt-6-astra` / `high`.
פרופיל: `RESEARCH`. בעלים: `evidence_sources`, `evidence_claims`.
תלויות לפני מימוש: אין; חוזים/ראיות חסרים מתועדים כפער.

## הודעה להעברה לסוכן
הכן dossier של דגם אחד שנבחר לפי פרוסת המשחק, או dossier זהות ראשוני אם Episode1 טרם נבחר. הבחֵן בין מפרט דגם, תת־דגם, שינויים במהלך שירות והוכחת נוכחות ביחידה.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/historical_evidence/DOMAIN.md`
- `context/game/domains/historical_evidence/roles/evidence_sources.md`
- `context/game/domains/historical_evidence/roles/evidence_claims.md`
- `docs/game/HISTORICAL_FIDELITY.md`
- `docs/game/REPO_MAP.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `evidence.source`
- `evidence.locator`
- `evidence.snapshot`
- `evidence.claim`
- `evidence.contradiction`
- `evidence.reconstruction`

## תוצרים
- טבלת שדות candidate עם source/locator, תוקף, יחידות, סתירות וחוסרים
- הפניות/קטעים מורשים; אין צורך להעתיק ספרים שלמים
- חבילת handoff ל־ground_platform/weapons_ballistics; בעל ההרכבה כותב את הגדרת הדגם
- ביקורת טענות במשימה נפרדת; אין שדרוג אוטומטי של legacy Atlas facts

## קבלה
- כל שדה משמעותי ניתן לאיתור במקור; unknown אינו מספר מומצא
- שם משפחה עמום אינו VariantId מאושר
- הפרדה בין evidence, reconstruction ו־gameplay; נוכחות ב־OOB מאומתת בנפרד

## כתיבה וגבולות
מקורות/claims/snapshots ייעודיים תחת historical_evidence; אין שינוי בגרף חי, בקוד סימולציה או בנתוני דגם סופיים.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
