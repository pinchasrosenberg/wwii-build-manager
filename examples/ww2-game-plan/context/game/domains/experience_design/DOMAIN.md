# קרבות, פעילויות וחוויית שחקן

מצב: דף כניסה לחבילת הקשר; אינו מתיר טעינת כל התיקייה ואינו מוכיח מימוש.

## פתיחה
- קרא `context/game/global/INVARIANTS.md` ואת חבילת Bxx שהוקצתה.
- טען רק את כרטיס התפקיד שלך ואת רשומות LegoId שהוקצו מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`.
- חוזים/ראיות גרסתיים ו־read/write scope יצורפו למשימה; אינם מומצאים מתוך שמות הממשקים.
- אם חוזה או מקור מחייב חסר, החזר פער ממוקד. עבודה סינתטית יכולה להמשיך רק בתחום שסומן כך.

## בעלויות
- `experience_loop` — `roles/experience_loop.md`
- `experience_interface` — `roles/experience_interface.md`

## טיפוסים בתחום
- `experience.interaction` — `experience_loop`: פעולה תחומה בעלת תנאי זכאות, אפשרויות, זמן, מחיר ותוצאה נתפסת.
- `experience.pacing` — `experience_loop`: בחירת הזדמנויות משחק ושקט לפי המצב הנוכחי ומטרת החוויה.
- `experience.profiles` — `experience_loop`: מדיניות עזרה, נגישות וקושי שנפרדת מנאמנות היסטורית ופירוט מודל.
- `player.desktop_input` — `experience_interface`: מיפוי מקלדת, עכבר ובקר לפעולות משמעותיות הניתנות לשינוי.
- `player.vr_boundary` — `experience_interface`: חוזה נפרד לראש/ידיים/גוף ולפעולות עם מתאם OpenXR ל־spike; בדיקת מכשיר ויציאת VR הן gates נפרדים.
- `player.comfort` — `experience_interface`: מדיניות מצלמה, תנועה, recenter, pause ונוחות בישיבה או בעמידה.
- `player.interface` — `experience_interface`: הוראות, כתוביות, משוב ויומן במבט מורשה עם מסלול מסכי ומרחבי.
- `player.evidence_inspector` — `experience_interface`: הצגת מקור, שחזור וזהות סינתטית לפי בקשת השחקן ובתחום המותר.
- `battle.template` — `experience_loop`: תבנית קרב נתונית הניתנת לשימוש חוזר: סיור, הגנה, התקפה או ליווי נבחרים בהרכבה מפורשת.
- `battle.objective` — `experience_loop`: יעד קרב מוגדר עם גורם אחראי, תנאי הצלחה/כישלון וחלופות מקומיות.
- `battle.condition` — `experience_loop`: תנאי ו־trigger הצהרתי מוגבל על זמן, מקום, פקודה או מצב מאושר.
- `battle.force_role` — `experience_loop`: תפקיד כוח כמו מגן, סייר, עתודה או מלווה עם שיוך יחידה ותחום סמכות.
- `battle.deployment` — `experience_loop`: נתוני מיקום התחלתי והגעה של כוחות בעלי חלון זמן, מקור ומדיניות reinforcement.
- `battle.phase` — `experience_loop`: שלב טקטי עם תנאי כניסה/יציאה, משימות מותרות וקשר לשלבים הבאים.
- `battle.anchor_policy` — `experience_loop`: מדיניות תחומה לפתרון התנגשות בין אילוץ היסטורי לתוצאות מקומיות.
- `battle.outcome` — `experience_loop`: תוצאה מקומית של קרב עם שינויים במצב, מקורות ותנאי סיום.
- `battle.difficulty_overlay` — `experience_loop`: שכבת עזרה וחוויית שחקן מעל תבנית קרב, ללא שינוי הגדרות היסטוריות.
- `player.body` — `experience_interface`: ייצוג וקלט של גוף, ראש וידיים; מפיק כוונת יציבה/תנועה/ישיבה בלבד. infantry_actions מחזיק תנועה ויציבה מוסמכות; ground_platform מחזיק תפוסת עמדה.
- `experience.activity` — `experience_loop`: מתכון פעילות: אכילה, תחזוקה, שמירה, אימון, מכתב או עזרה, עם משך וחברה.

## גבול כתיבה
בעל התחום צורך ממשקים של תחומים אחרים. הוא אינו כותב בהם או מקבל את קוד המקור שלהם אוטומטית. חבילה היסטורית נבדקת בנפרד ממימוש ומהנכס החזותי. נתיבי הפלט ברישום הם יעדים עתידיים, לא קבצים קיימים.
