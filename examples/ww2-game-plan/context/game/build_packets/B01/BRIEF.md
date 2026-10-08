# B01 — טנק ורכב כהרכבה חוזרת

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-sol` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `IMPLEMENT`. בעלים: `ground_platform`, `ground_powertrain`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
בנה קודם tracked vehicle סינתטי עם גוף, תנועה, צריח ריק ועמדת צוות. חבר נשק דרך חוזה B02 בלי לשכתב ירי. הוסף מתכון שני עם נתונים שונים להוכחת reuse; נתוני טנק אמיתי רק אחרי B03.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/ground_vehicles/DOMAIN.md`
- `context/game/domains/ground_vehicles/roles/ground_platform.md`
- `context/game/domains/ground_vehicles/roles/ground_powertrain.md`
- `docs/game/LEGO_ARCHITECTURE.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `equipment.engine`
- `equipment.transmission`
- `equipment.wheel`
- `equipment.track`
- `equipment.suspension`
- `mobility.tracked`
- `mobility.wheeled`
- `equipment.chassis`
- `equipment.armor_plate`
- `equipment.turret`
- `equipment.fuel_tank`
- `equipment.crew_station`
- `equipment.ground_vehicle`
- `equipment.access_port`
- `equipment.stowage`

## תוצרים
- מנגנון ניידות והרכבת פלטפורמה בשתי משימות כתיבה נפרדות
- שני מתכוני fixture סינתטיים, manifest, test scene ותמונת preview אם כלי renderer זמין
- חיבורי mount, crew, hatch, stowage, damage ו־VisualBinding עם gaps מפורשים

## קבלה
- אותו loader לשתי תצורות; אין if לפי שם קרב או יצרן
- רטיבות/מדרון נצרכים מ־TerrainSample; נשק מצורף דרך mount
- save שומר דלק, תחמושת, פגיעות, תפוסת צוות ו־VariantId
- טנק שנראה כדגם אחר נדחה לפני promotion

## כתיבה וגבולות
רק נתיבי ground_vehicles של LegoIds שהוקצו; powertrain ו־platform בקבוצות קבצים נפרדות. אין כתיבה ל־weapons_effects, characters או terrain.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
