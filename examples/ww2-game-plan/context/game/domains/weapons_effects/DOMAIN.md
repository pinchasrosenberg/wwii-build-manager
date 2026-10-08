# נשק, תחמושת ואפקטים

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `weapons_ballistics` — `roles/weapons_ballistics.md`
- `weapons_damage` — `roles/weapons_damage.md`

## טיפוסים בתחום
- `equipment.gun` — `weapons_ballistics`: הגדרת כלי ירייה עם קנה, תושבת, הזנה ומאפייני וריאנט.
- `equipment.projectile` — `weapons_ballistics`: קליע או פגז עם מסה, ממדים, סוג ופרמטרי השפעה מבוססים.
- `equipment.optic` — `weapons_ballistics`: כוונת או מכשיר אופטי עם מגבלות שדה ראייה, הגדלה ויישור.
- `weapons.ammunition_compatibility` — `weapons_ballistics`: התאמת תחמושת, מטען, הזנה ותושבת לווריאנט נשק.
- `weapons.firing_reload` — `weapons_ballistics`: מצב טעינה, ירי, טעינה מחדש והפרעה לפעולה של נשק קטן או תותח.
- `weapons.ballistics` — `weapons_ballistics`: מסלול קליע ופתרון פגיעה בתחום מרחק ומהירות שהמודל תומך בו.
- `effects.armor_interaction` — `weapons_damage`: השפעת פגיעה על לוח וחלק פנימי לפי תחמושת, זווית ומודל מוצהר.
- `effects.blast` — `weapons_damage`: השפעת הדף ורסיסים במעטפת מקומית עם כיסוי ומגבלות קירוב.
- `effects.fire` — `weapons_damage`: הצתה, בעירה ודעיכה בתחומים נתמכים עם צריכת חומר ונזק מוצהר.
- `effects.suppression` — `weapons_damage`: המרת אש קרובה וגירויים מאושרים לאירוע דיכוי זמני של פעילות.
- `equipment.barrel` — `weapons_ballistics`: קנה נשק בעל אורך, קדח, מסה ונקודות חיבור לפי וריאנט.
- `equipment.breech` — `weapons_ballistics`: מכלול סגירה ותפעול של בית הבליעה, ידני או אוטומטי, לפי תצורה נתונית.
- `equipment.feed_system` — `weapons_ballistics`: מחסנית, חגורה או הזנה אחרת עם קיבולת, תאימות ומצב נוכחי.
- `equipment.weapon_stock` — `weapons_ballistics`: קת ומשטחי אחיזה הנקשרים למעטפת נשק ול־anchors אנושיים.
- `equipment.weapon_action` — `weapons_ballistics`: הגדרת משפחת מנגנון בריחי/ידני, חצי־אוטומטי או אוטומטי ופעולותיו.
- `equipment.weapon_mount` — `weapons_ballistics`: הגדרת חיבור נשק מקומי לאחיזה, חצובה או פלטפורמה. platform מחזיק transform עולמי ומצב צירי צריח; הנשק צורך אותם.
- `equipment.throwable` — `weapons_ballistics`: פריט משחק נזרק המורכב מפעולה, מטען, תנועה ואפקט; ללא פרטי בנייה בעולם האמיתי.
- `effects.obscurant` — `weapons_damage`: נפח עשן/אבק שמשפיע על ראות לאורך זמן ומפיק מצב להצגה.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
