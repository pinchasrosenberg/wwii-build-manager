# אנשים, זיכרון ויחסים

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `character_identity` — `roles/character_identity.md`
- `character_memory` — `roles/character_memory.md`
- `character_social` — `roles/character_social.md`

## טיפוסים בתחום
- `character.identity` — `character_identity`: CharacterId רציף עם שם, רקע, מעמד אמיתי או סינתטי ומקורות מפורשים.
- `character.commitments` — `character_identity`: מחויבויות, תפקידים והבטחות מתמשכות של אדם לאורך זמן.
- `character.memory` — `character_memory`: זיכרון מתמיד של אירוע נתפס, עדים, זמן ומקור הידיעה.
- `character.knowledge` — `character_memory`: מאגר אמונות וידיעות של אדם עם מקור, זמן מסירה ואפשרות לטעות.
- `character.relationship` — `character_social`: קשר מכוון בין אנשים המשתנה בעקבות פעולות שנחוו.
- `character.dialogue` — `character_social`: דיבור ותגובות דרך הצעה תחומה, תנאי זכאות ובדיקת ידע.
- `character.routines` — `character_social`: לוח פעילויות של שינה, אוכל, שמירה, עבודה ופנאי עם הפרעות.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
