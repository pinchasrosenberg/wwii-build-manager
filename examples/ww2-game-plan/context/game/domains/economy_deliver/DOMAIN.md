# בנייה, ספקים ועלויות

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `economy_provider` — `roles/economy_provider.md`

## טיפוסים בתחום
- `build.capability_provider` — `economy_provider`: אותו חוזה ביצוע מקומי או adapter ל־Deliver עבור משימת בנייה מחוץ ל־runtime.
- `build.quote_reservation` — `economy_provider`: quote מאושר ורזרבה לפני פעולה בתשלום עם זהות בקשה יציבה.
- `build.investment` — `economy_provider`: בחירת השקעת fidelity לפי חוסר היסטורי, תרומה לחוויה, עלות ושימוש חוזר.
- `build.settlement` — `economy_provider`: קבלה, reconciliation וסגירת עלות ספק מול תוצר ו־quote.
- `build.deliver_adapter` — `economy_provider`: מתאם פרוטוקול Deliver אמיתי מאחורי חוזה ספק קיים ללא זליגת internals למשחק.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
