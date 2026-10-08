# B04 — מזג אוויר, קרקע והשפעות

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-sol` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `IMPLEMENT`. בעלים: `weather_system`, `terrain_world`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
בנה דגימת סביבה אחת שממנה נובעים גשם/רוח/ראות, מצב קרקע ותצוגה. הדגם הסינתטי הראשון כולל מעבר מיבש לרטוב ושינוי ראות; בלי להציגו כמזג אוויר היסטורי.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/weather/DOMAIN.md`
- `context/game/domains/weather/roles/weather_system.md`
- `context/game/domains/geospatial_temporal/DOMAIN.md`
- `context/game/domains/geospatial_temporal/roles/terrain_world.md`
- `docs/game/HISTORICAL_FIDELITY.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `weather.sample`
- `weather.timeline`
- `weather.precipitation`
- `weather.wind`
- `weather.visibility_cloud`
- `weather.thermal`
- `weather.effects`
- `world.terrain`
- `world.surface_material`
- `world.surface_state`

## תוצרים
- WeatherSample/timeline ו־modifiers בבעלות weather_system
- SurfaceState המתעדכן אצל terrain_world; fixture לחיכוך/מעבר וראות
- חוזה לצרכני רכב/אדם/AI/נכסים; אין כתיבה ישירה במצב שלהם

## קבלה
- שמירה וחידוש משחזרים דגימה ורטיבות
- renderer ו־AI מקבלים אותו מקור ראות; חלקיקי גשם לבדם אינם השלמה
- רכב מגיב למשטח; שינוי difficulty אינו משנה HistoricalTruth
- פער במדידת מזג אוויר נשמר כפער/שחזור

## כתיבה וגבולות
weather ומקטע surface_state/terrain שהוקצה בלבד; תיקוני צרכנים נעשים בידי בעליהם.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
