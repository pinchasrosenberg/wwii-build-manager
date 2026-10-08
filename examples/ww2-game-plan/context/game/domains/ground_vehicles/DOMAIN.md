# רכב וטנקים

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `ground_powertrain` — `roles/ground_powertrain.md`
- `ground_platform` — `roles/ground_platform.md`

## טיפוסים בתחום
- `equipment.engine` — `ground_powertrain`: ליבת מנוע משותפת: אספקת הספק לציר, צריכת משאב ומצב תקינות; פרמטרים לפי וריאנט.
- `equipment.transmission` — `ground_powertrain`: יחסי העברה וכיוון בין מקור הספק להינע במודל מוצהר.
- `equipment.wheel` — `ground_powertrain`: גלגל בעל מידה, חומר ומגע המשמש כלי רכב ויישומים נוספים.
- `equipment.track` — `ground_powertrain`: זחל עם תחום מגע, מצב תקינות וממשק העברת כוח.
- `equipment.suspension` — `ground_powertrain`: מענה עומס ומגע של מתלה עבור הרכב שנבחר.
- `mobility.tracked` — `ground_powertrain`: תנועה קרקעית באמצעות זוג זחלים או תצורה מאושרת אחרת.
- `mobility.wheeled` — `ground_powertrain`: תנועה קרקעית גלגלית לפי אחיזה, עומס ומעטפת כלי הרכב.
- `equipment.chassis` — `ground_platform`: שלדה עם מסה, מידות ונקודות חיבור למרכיבי הרכב.
- `equipment.armor_plate` — `ground_platform`: לוח מיגון בעל גאומטריה, חומר ועובי לפי מקור או קירוב מוצהר.
- `equipment.turret` — `ground_platform`: צריח עם טבעת חיבור, מגבלות צידוד והגבהה, תושבות ועמדות צוות.
- `equipment.fuel_tank` — `ground_platform`: מכל דלק עם קיבולת, סוג חומר, מיקום ומצב דליפה.
- `equipment.crew_station` — `ground_platform`: עמדת נהג, תותחן או איש צוות עם תפוסה, גישה ושדה עבודה. כולל קישור לפתח, נקודות כניסה/יציאה, מבט, ישיבה, אחיזה וגישה פנימית.
- `equipment.ground_vehicle` — `ground_platform`: הרכבת וריאנט ו־instance של טנק, משאית או רכב אחר מרכיבים נעולים.
- `equipment.access_port` — `ground_platform`: פתח/דלת/מדף של כלי רכב עם מצב, תנאי גישה ונקודות כניסה/יציאה.
- `equipment.stowage` — `ground_platform`: מכל אחסון דלק, תחמושת או מטען עם קיבולת, משקל וגישה.
- `mobility.hybrid` — `ground_powertrain`: הרכבת ניידות גלגלים וזחלים לרכב חצי־זחלי בלי fork נפרד של מנוע.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
