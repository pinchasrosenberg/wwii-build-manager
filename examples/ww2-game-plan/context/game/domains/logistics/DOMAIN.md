# אספקה ותחזוקה

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `logistics_supply` — `roles/logistics_supply.md`
- `logistics_maintenance` — `roles/logistics_maintenance.md`

## טיפוסים בתחום
- `logistics.stock` — `logistics_supply`: חשבון מלאי בעל סוג, כמות, יחידה, בעלים ומיקום.
- `logistics.transfer` — `logistics_supply`: העברת אספקה אטומית בין מלאים עם קיבולת, אובדן וזמן.
- `logistics.supply_route` — `logistics_supply`: הקצאת תובלה ודרך למענה על ביקוש בעל deadline.
- `logistics.maintenance` — `logistics_maintenance`: בדיקה ותחזוקה מתוכננת לפי ציוד, זמן, כשירות וחלקים.
- `logistics.repair` — `logistics_maintenance`: תיקון כשל רכיב באמצעות יכולת איש צוות, גישה וחלקי חילוף.
- `logistics.resource_definition` — `logistics_supply`: זהות וכמות של מזון, מים, דלק, תחמושת וחלפים עם יחידות ותאימות.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
