# חיילים וציוד אישי

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `infantry_actions` — `roles/infantry_actions.md`
- `infantry_casualty` — `roles/infantry_casualty.md`

## טיפוסים בתחום
- `actor.human` — `infantry_actions`: גוף אדם סימולטיבי בעל זהות יציבה, ממדים, מצב פעולה ויכולות בסיס.
- `infantry.carried_equipment` — `infantry_actions`: לבוש, ציוד אישי ונשק נישא התואמים יחידה, תפקיד, מקום וזמן.
- `infantry.locomotion` — `infantry_actions`: הליכה, פנייה, כריעה ומעבר בסיסי מול מעטפת גוף ומשטח.
- `infantry.squad_formation` — `infantry_actions`: תנועה, המתנה והתקבצות של חוליה עם מרחקים ותפקידים.
- `infantry.injury` — `infantry_casualty`: פציעה, אובדן יכולת ומוות כמצבים מתמידים בעלי סיבה וזמן.
- `infantry.care` — `infantry_casualty`: פעולת סיוע מוגבלת שמחייבת אדם מתאים, זמן ומשאבים.
- `infantry.condition` — `infantry_casualty`: עייפות, מאמץ, שינה, רעב/צמא וחשיפה כמודל משחק מוצהר; נפרד מפציעה.
- `infantry.wearable` — `infantry_actions`: מדים, קסדה, נעליים, תיק וציוד אישי עם תוקף דגם, slots ומשקל.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
