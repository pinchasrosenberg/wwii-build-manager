# B02 — נשק, פעולות ירי ואפקטים

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-sol` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `IMPLEMENT`. בעלים: `weapons_ballistics`, `weapons_damage`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
בנה מכלול נשק מנתונים, feed/chamber/action ומחזור reload עם סמכות אחת לתחמושת. ראשית שני fixtures עם מנגנון משותף; לאחר מכן דגם אחד ורכיב מקלע הדרושים לפרוסה, לפי B03.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/weapons_effects/DOMAIN.md`
- `context/game/domains/weapons_effects/roles/weapons_ballistics.md`
- `context/game/domains/weapons_effects/roles/weapons_damage.md`
- `docs/game/LEGO_ARCHITECTURE.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `equipment.gun`
- `equipment.projectile`
- `equipment.optic`
- `weapons.ammunition_compatibility`
- `weapons.firing_reload`
- `weapons.ballistics`
- `effects.armor_interaction`
- `effects.fire`
- `effects.suppression`
- `equipment.weapon_action`
- `equipment.weapon_mount`
- `effects.obscurant`
- `equipment.barrel`
- `equipment.breech`
- `equipment.feed_system`
- `equipment.weapon_stock`

## תוצרים
- מכלול נשק/רכיבי קנה, בית בליעה, הזנה, קת ותחמושת; action state machine
- מודול אפקטי משחק במשימה נפרדת בבעלות weapons_damage, אחרי סקירת DEEP
- סצנת בדיקה, חוזה כוונה/פגיעה, אירועים לתצוגה וחיבור לרכב/חייל

## קבלה
- ירי/טעינה/ביטול לא משכפלים תחמושת; פעולה לא תקפה נדחית
- תחמושת/mesh/part שאינם שייכים לווריאנט נדחים
- אפקט מוחל פעם אחת בידי בעל מצב הנפגע; אנימציה אינה מקור לנזק
- two-variant reuse, save במהלך reload ותצוגת עשן מול perception נבדקים

## כתיבה וגבולות
רק weapons_effects; ballistics כותב נשק/תחמושת/מסלול; damage כותב solver של אפקטים. רכיבי barrel/breech/feed/stock נבחרים מתוך הרישום לפני שיגור.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
