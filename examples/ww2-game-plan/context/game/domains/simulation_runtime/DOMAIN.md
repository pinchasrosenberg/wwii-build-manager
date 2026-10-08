# מנוע, הרכבה והתמדה

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `runtime_core` — `roles/runtime_core.md`
- `runtime_continuity` — `roles/runtime_continuity.md`

## טיפוסים בתחום
- `runtime.ecs` — `runtime_core`: רישום רכיבים וזהויות עם בעלות כתיבה מפורשת ומבטים מורשים.
- `runtime.schedule` — `runtime_core`: תזמון tick קבוע, סדר מערכות ושעונים מקומיים מוכרזים.
- `runtime.physics_port` — `runtime_core`: גבול physics/navigation המקבל פקודות ומחזיר תוצאות מאושרות מה־backend הנעול.
- `runtime.events` — `runtime_core`: סדר אירועים, סיבות, ייחודיות ו־RNG בתחום determinism מפורש.
- `runtime.actor_projection` — `runtime_core`: סינון מצב עולם למבט שחקן או NPC על בסיס מידע שנמסר בלבד.
- `runtime.episode_loader` — `runtime_core`: טעינת EpisodeSpec, רכיבים ונכסים לפי גרסאות, hashes והתקנות מורשות.
- `runtime.lod` — `runtime_continuity`: מעבר בין רמות סימולציה ושמירת מצב של יחידים וקבוצות.
- `runtime.save` — `runtime_continuity`: צילום מצב וטעינה עם נעילת תוכן ו־schema ומיגרציה מפורשת.
- `runtime.replay` — `runtime_continuity`: בדיקת שחזור החלטות לפי פקודות ותוצאות קודמות, ובנפרד הרצה פיזיקלית חוזרת.
- `runtime.time_acceleration` — `runtime_continuity`: קידום זמן מוסכם עם עצירה לפני אירוע מקומי משמעותי ועיבוד אילוצים.
- `runtime.battle_evaluator` — `runtime_core`: הערכת תנאים ושלבי תבנית נתונית בסדר אירועים מוגדר, בלי קוד אפיזודה שרירותי.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
