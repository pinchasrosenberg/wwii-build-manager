# מראה, הנפשה, קול וכלי תצוגה

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `assets_visual` — `roles/assets_visual.md`
- `assets_motion` — `roles/assets_motion.md`
- `assets_audio` — `roles/assets_audio.md`

## טיפוסים בתחום
- `asset.mesh` — `assets_visual`: בניית מודל גוף, מבנה או ציוד התואם וריאנט עם scale, collision ו־LOD.
- `asset.material` — `assets_visual`: חומרים וטקסטורות תואמי דגם עם profile desktop ותקציבי VR עתידיים.
- `asset.import_manifest` — `assets_visual`: נעילת תוכן, רישיון, מקור, פורמט והגדרות ייבוא ל־Godot.
- `asset.rig` — `assets_motion`: שלד, anchors לידיים ואחיזה וקישור גוף למלבוש או ציוד.
- `asset.animation` — `assets_motion`: לוקומוציה, מחוות, מבט ופעולות המחשה הנגזרות ממצב פעולה מאושר.
- `asset.spatial_audio` — `assets_audio`: קול סביבתי, נשק, צעדים ומקורות קול במיקום עולם עם תקציבי ביצוע.
- `asset.voice_subtitles` — `assets_audio`: תוכן קולי וכתוביות שפה עם תזמון, זכויות וזיקה להצעת דיבור מאושרת.
- `asset.visual_binding` — `assets_visual`: קישור מפורש בין VariantId, חלקים, sockets, mesh, חומר ו־LOD.
- `asset.vfx` — `assets_visual`: אפקטים חזותיים לאירוע ירי/פגיעה, עשן, אבק, אש ומשקעים.
- `asset.environment_light` — `assets_visual`: שמיים, שמש, תאורת פנים/חוץ, פנסים וחשיפה אסתטית לפי מצב עולם.
- `asset.decals` — `assets_visual`: סימני בוץ, עקבות, שחיקה ופגיעות, מוגבלים בתקציב ומשך חיים.
- `asset.catalog_preview` — `assets_visual`: כלי פיתוח לקטלוג, בדיקת רכיבים, variant inspector ותצוגת sandbox.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
