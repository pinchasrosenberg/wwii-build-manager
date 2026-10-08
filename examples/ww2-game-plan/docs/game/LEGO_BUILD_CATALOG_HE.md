# קטלוג הלגו לבניית המשחק — בעלויות, דגמים וחבילות עבודה

תאריך: 27.09.2026 · גרסה: 1.0 · סטטוס: מפרט בנייה, לא רכיבים שכבר מומשו.

**זה הקובץ שממנו מחלקים את הבנייה.** הוא מגדיר את חלקי העולם, מי בונה כל חלק, אילו חלקים משותפים לדגמים שונים, איך מציגים אותם ואיזה קונטקסט מקבל כל סוכן. רשימת הטיפוסים המלאה מופיעה בהמשך; חבילות השיגור נמצאות גם תחת `context/game/build_packets/`.

הקובץ כולל 158 טיפוסי לגו, 31 כתובות בעלות, 17 תחומים ו־10 חבילות עבודה. להתחלה קרא את סעיף 2; לפרטי הטנק/הנשק/הקרבות/מזג האוויר את סעיפים 3–7; לרשימה המלאה ולכרטיסי הסוכנים את סעיפים 13–15.

המלצה מעשית: Codex Sol לבניית הקוד; Claude Opus למחקר הדגמים ובדיקת מקורות; Claude Sonnet לעיצוב פעילויות ותבניות קרב; Astra לחוזים, לשילוב ולהכרעות מורכבות. זו בחירת תפקידים לפרויקט, ולא טענה שנערך benchmark בין המודלים על המשחק.

## 1. איך טנק אחד הופך ללגו שניתן להשתמש בו שוב

יש חמש שכבות שונות:

| שכבה | דוגמת טנק | מה בונים פעם אחת |
|---|---|---|
| מנגנון | הנעה בזחלים, צריח, ירי, נזק, עמדת צוות | קוד כללי עם חוזה ובדיקות |
| הגדרת דגם היסטורי | דגם ותת־דגם מדויקים של טנק, בתקופת תוקף מוגדרת | נתוני הרכבה, הפניות לרכיבים ולראיות; בדרך כלל ללא קוד חדש |
| הרכבה | גוף + הנעה + נשק + תחמושת + צוות + חיבורים | מתכון מאומת שמחבר יכולות קיימות |
| ייצוג | מודל תלת־ממד, חומרים, שלד, אנימציות, צלילים ו־LOD | חבילת נכסים המתאימה לאותו VariantId |
| מופע בעולם | הטנק המסוים של היחידה: דלק, פגיעות, אנשי צוות ומיקום | מצב שמירה; לא סוכן פיתוח חדש |

אין סוכן נפרד לכל גלגל, לכל חייל או לכל טנק בשדה. `ground_powertrain` מחזיק את טיפוס הגלגל/הזחל; מאות מופעים צורכים את אותו מימוש. במנוע, חלק פיזי קטן יכול להיות רשומה או שדה בתוך רכיב, ואינו חייב להיות entity או node נפרד. מפרקים לקוד נפרד רק כשיש התנהגות, שימוש חוזר או בעלות נפרדת.

ה־Episode Builder משתמש **רק בטיפוסים ובגרסאות הרשומים**. אם חסר סוג אמיתי של התנהגות, הוא מפיק `CapabilityGap`; בעל התחום מוסיף יכולת כללית עם חוזה ובדיקות; ורק אז האפיזודה צורכת אותה. הוספת צבע, מספר טקטי, דגם או מיקום אינה סיבה להעתיק מנגנון. אין דרך סבירה להבטיח היום רשימה סופית של כל צורך עתידי; זהו אוצר הרכיבים המחייב של v1, עם מסלול הרחבה מבוקר.

## 2. למי לשלוח עכשיו

במודלים בטבלה, `Sol` פירושו `gpt-6-sol` עם `high`; `Astra` הוא `gpt-6-astra`; `Opus` הוא `claude-opus-5-5`; `Sonnet` הוא `claude-sonnet-5`. אם Sol 6 אינו זמין ב־Codex, המסלול הזמין בסביבה הנוכחית הוא `gpt-5.6-sol` עם `high`. Claude הוא יעד להרצה בסביבה שתומכת בו; כלי תתי־הסוכנים בשיחה זו אינו מריץ Claude.

| חבילה | מה לשלוח לבנייה | בעל התוצר | מודל ראשון | קונטקסט פתיחה | מתי |
|---|---|---|---|---|---|
| B00 | חוזי החיבור, יחידות, זהויות ו־host קטן | `runtime_core` | Astra high; xhigh כשיש הכרעה בין תחומים | `context/game/build_packets/B00/BRIEF.md` | ראשון; חוסם כתיבת קוד תלוי |
| B01 | בסיס טנק ורכב: גוף, הנעה, צריח, צוות וחיבור נשק | `ground_platform`; משימת משנה נפרדת ל־`ground_powertrain` | Sol high | `…/B01/BRIEF.md` | לאחר הקפאת חוזי B00 |
| B02 | בסיס נשק: פעולת ירי/טעינה, תחמושת, פגיעה ואפקטים | `weapons_ballistics`; `weapons_damage` בקבצים נפרדים | Sol high; Astra high לתכנון מודל הנזק | `…/B02/BRIEF.md` | במקביל לטנק |
| B03 | מחקר דגמי טנקים ונשק והוכחת התאמה לזמן/מקום | `evidence_sources` ו־`evidence_claims`, במשימות נפרדות | Opus high; חלופה כאן Astra high | `…/B03/BRIEF.md` | יכול להתחיל עם B00 |
| B04 | קרקע, משטחים, מזג אוויר והשפעתם | `weather_system`; `terrain_world` כותב את הקרקע | Sol high | `…/B04/BRIEF.md` | לאחר חוזי דגימת סביבה |
| B05 | תבניות קרב, מטרות, פעילויות שקטות וקצב | `experience_loop`; loader בבעלות `runtime_core` | Sonnet high לעיצוב; Sol high למימוש | `…/B05/BRIEF.md` | עיצוב מוקדם; שילוב אחרי החוזים |
| B06 | חיילים, חברי יחידה, תפיסה, פקודות וזיכרון בסיסי | `infantry_actions` עם בעלי הדמויות/AI | Sol high; Sonnet high לכתיבת אינטראקציות | `…/B06/BRIEF.md` | נדרש כבר לפרוסת המשחק הראשונה |
| B07 | מודלים, חומרים, ריג, אנימציה וצלילים | `assets_visual`, `assets_motion`, `assets_audio` כל אחד בתוצריו | Sol high לכלי pipeline; Sonnet high לתיאור/ביקורת | `…/B07/BRIEF.md` | מלאי נכסים מיד; חיבור לאחר B00 |
| B08 | הצגה לשחקן: גוף, מצלמה, פעולות, UI והכנה ל־VR | `experience_interface` | Sol high | `…/B08/BRIEF.md` | M1, לפני השקעה בנכסים מפורטים |
| B09 | שמירה מוקדמת; בהמשך הרכבה ובדיקות היסטוריה וחוויה | `runtime_continuity` לשמירה; reviewers עצמאיים לקבלה | Sol high לשילוב; Astra/Opus high לבדיקה | `…/B09/BRIEF.md` | seam לאחר B00; שילוב מלא בסוף |

כל חבילה היא קבוצת משימות: היא אינה מעניקה לסוכן אחד בעלות על כל התחומים שמופיעים בה. המנהל מפצל אותה לכותב אחד לכל קבוצת קבצים. לפני שיגור נועלים רשימת רכיבים, גרסאות חוזים, קובצי קריאה וקובצי כתיבה. הטבלאות אינן מפעילות משימות, מתקינות מנוע או מזמינות עבודה בתשלום.

שלוש הקצאות שחשוב לא להחמיץ: B00 חוזר למשימת `runtime.actor_projection` ו־`runtime.battle_evaluator` אחרי עיצוב התבנית ב־B05; B06 כולל משימות נפרדות למלאי/העברה, סמכות/פקודות, ידע ושיחה; B09 מתחיל בחוזה snapshot ובבדיקת שמירה סינתטית מיד אחרי החוזים. בדיקות הרכיבים צורכות אותו מוקדם, והשמירה המשולבת נבדקת בסוף. כך אין תלות מעגלית בין בניית רכיב לבין שילובו.

## 3. הטנק — חלוקת בנייה מדויקת

**כתובת אחת לטנק מורכב: `ground_platform`.** הוא אחראי לכך שהרכב מתחבר ועובד; הוא צורך את ההנעה, הנשק, הקשר, אנשי הצוות והנכסים דרך חוזים. הוא אינו משכתב אותם בעצמו.

| חלק | מה כלול | הבעלים הכותב | מי מספק מידע/תלות |
|---|---|---|---|
| גוף ושלדה | ממדים, מסה, מסגרת צירים, נקודות חיבור, collision ותאים ברמת הפירוט שנבחרה | `ground_platform` | חוקר דגם; `assets_visual` מספק גאומטריה |
| לוחות שריון | אזור, חומר, עובי/זווית אם ידועים, תחולת דגם | `ground_platform` | `evidence_claims`; חישוב תוצאת הפגיעה אצל `weapons_damage` |
| צריח ותושבות | צירי תנועה, מגבלות מכניות, נקודות התקנת נשק | `ground_platform` | `assets_motion` מנפיש את המצב; אינו קובע אותו |
| מנוע ומערכות עזר | כוח זמין, מצב חום/תקלה, דלק, קירור לפי הצורך | `ground_powertrain` | נתוני מקור; קירוב מוצהר במקום מפרט חסר |
| תמסורת והנעה סופית | העברת פקודה לתנועה, מצבי תקלה | `ground_powertrain` | חוזה כוח/תנועה |
| גלגלים, זחלים ומתלים | מגע עם הקרקע, החלקה, ניידות, ייצוג נזק | `ground_powertrain` | `TerrainSample` ו־`SurfaceState` |
| מיכל דלק ואחסון תחמושת | קיבולת, מלאי, מיקומים מופשטים/מפורטים, גישה | `ground_platform` | logistics מעביר מלאי; effects מחזיר הצעת נזק |
| תותח, מקלע, כוונת ותחמושת | פריטי נשק קיימים המותקנים בטנק | `weapons_ballistics` | platform מספק MountTransform; לא נוצר "ירי טנק" כפול |
| נזק, אש ועשן | solver מחזיר אפקטים; platform מעדכן את מצב החלק הפגוע | `weapons_damage` לאפקט; `ground_platform` למצב הרכב | רשימת חלקים וחומרים; אש/עשן חזותיים אצל assets |
| עמדות צוות | נהג, מפקד ושאר עמדות בהתאם לדגם; סמכויות וקווי ראייה | `ground_platform` | זהות האנשים אצל `character_identity`; החלטות אצל AI |
| רדיו ופקודות | תקשורת מוגבלת, עיכוב, מסירה והוראות | `command_structure` לתוכן/סמכות פקודה; `command_signals` לתקשורת ומסירה | המעטפת הפיזית של הרדיו משויכת לנכס |
| כניסה, יציאה וטיפול ברכב | נקודות גישה, בדיקה, מילוי, תיקון | platform לגישה; `logistics_maintenance` לטיפול | פעולת שחקן, זמינות אדם/כלי/חלף |
| מראה ותנועה | mesh, textures, LOD, turret/track rig, פנים אם נדרש | `assets_visual` / `assets_motion` | VariantId ומצב סימולציה; ללא שינוי היסטוריה כדי להתאים asset |
| קול | מנוע, תמסורת, זחל, פנים, ירי ומכות | `assets_audio` | אירועים ומהירות/עומס; לא לולאת קול קבועה לכל רכב |

דלק ותחמושת לא מוחזקים בשני מאגרים מתחרים: הלוגיסטיקה מבקשת העברה, והבעלים של container היעד מאשר עדכון אטומי. בדומה לכך, solver נזק אינו כותב ישירות בריאות של כל דומיין; הוא מפיק אפקט שבעל מצב הרכב או האדם מחיל פעם אחת.

### דגמי טנקים: נתונים ולא fork של קוד

רשימת פתיחה למחקר: Panzer III Ausf. J, Panzer IV Ausf. H, Panther Ausf. G, Tiger I, M4A1, M4A3, T-34/76, T-34/85, Churchill, Cromwell. אלה **שמות חיפוש ראשוניים**, לא הגדרות מאומתות או אישור נוכחות באפיזודה. שמות משפחה כמו Churchill, M4A3 ו־T-34/76 מחייבים פיצול לתת־דגם, תצורה ותקופת ייצור לפני פרסום VariantId. אין במפרט הזה טענות על ביצועים, תאריכים או סדר כוחות של הדגמים.

חוקר B03 מגיש candidate dossier לכל דגם: זהות ושמות חלופיים, תתי־דגמים, שדות עם מקורות ומיקום במקור, סתירות, נתונים חסרים, ותוקף זמן/מקום. `ground_platform` מחבר ממנו VariantDefinition ונועל את רכיבי המשנה; `assets_visual` מחבר VisualBinding לאותו מזהה; reviewer עצמאי מאמת את ההתאמה. נוכחות של דגם ביחידה מסוימת דורשת ראיה נוספת לעצם מפרט הדגם.

מתחילים בדגם אחד הדרוש לפרוסה, ואז בדגם שני כדי להוכיח שימוש חוזר. גם רכב גלגלי, חצי־זחלי, משוריין, תותח מתנייע או משאית משתמשים בחלקים משותפים; דפוס ניידות חדש נרשם כיכולת במקום להתחזות לטנק.

## 4. כלי הנשק — משפחות מנגנונים ודגמים

`weapons_ballistics` הוא הבעלים של מכלול הנשק ושל הגדרות הדגמים. מחקר העובדות אצל צוות הראיות, אפקט הפגיעה אצל `weapons_damage`, והחזקה/טעינה פיזית בידי האדם אצל `infantry_actions` ו־`assets_motion`.

| לגו | שימוש חוזר | כלל החיבור |
|---|---|---|
| קנה ובית בליעה | נתוני דגם ופרופיל ירי | פרופיל משחק מופשט; אין צורך בסימולציית ייצור או תרמודינמיקה מלאה |
| מנגנון פעולה | ידני/בריחי, חצי־אוטומטי, אוטומטי; מצבי safe/ready/reload/fault | מכונת מצבים אחת עם פרמטרים; חריג אמיתי הופך להרחבה כללית |
| הזנה | מחסנית, קליפס, סרט או טעינה יחידנית לפי הדגם | מעקב מפורש אחרי מקור תחמושת, בית בליעה ופעולה בתהליך |
| אחיזה ותושבת | קת, ידית, חצובה, תושבת רכב, שתי ידיים | פעולת Gameplay זהה; desktop ו־VR ממפים אליה קלט שונה |
| תחמושת וקליע | תאימות, מלאי, תנועה ואפקטי משחק | אין מעבר תחמושת בין דגמים רק משום ששמותיהם דומים |
| כוונת ורכיבי תצפית | קו כוונה, שדה ראייה, מצב שימוש | camera view צורך את המידע; אינו הבעלים שלו |
| ירי, טעינה, פליטה ותקלה | רצף פעולה, חיווי, צריכת משאבים | אירוע אחד מוסמך; האנימציה והקול נגזרים ממנו |
| מסלול ופגיעה | query בזמן/מרחב, פגיעה במשטח ותגובה | תוצאה חוזרת עם אותו seed ותנאי בדיקה באותה פלטפורמה |
| אפקטים | דיכוי, נזק, עשן/אש, חומר שנפגע | תיאור משחק כללי ולא מדריך שימוש מבצעי בעולם האמיתי |

רשימת דגמים ראשונית למחקר, ולא מלאי שחייבים לבנות מיד:

| משפחה | דוגמאות לחבילות נתונים עתידיות |
|---|---|
| רובים בריחיים | Karabiner 98k, Lee–Enfield No. 4 Mk I, Mosin–Nagant 91/30 |
| רובים חצי־אוטומטיים | M1 Garand; דגם נוסף רק לפי צורך האפיזודה |
| תת־מקלעים | MP 40, Sten Mk II, PPSh-41, Thompson M1A1 |
| מקלעים | Bren Mk I, MG 34, MG 42, Browning M1919A4 |
| משפחות נוספות לפי צורך | אקדח, רימון, נשק נ"ט, מרגמה, תותח שדה, נשק מותקן בכלי רכב/כלי שיט/כלי טיס |

גם כאן השמות הם רשימת זיהוי למחקר בלבד. שדה שלא נבדק לא מקבל מספר מומצא. פרוסת M1 יכולה להשתמש ב־`fixture.weapon.alpha` סינתטי; אסור לקדם אותו כדגם היסטורי. מבחן שימוש חוזר: החלפת חבילת דגם משנה את הזהות, המראה והנתונים בלי שינוי loader ובלי תנאי בקוד לפי שם הקרב.

## 5. סוגי קרבות הם הרכבות של פעולות, לא תסריטים קשיחים

`experience_loop` מחזיק את **תבנית החוויה והקרב**. `command_structure` מחזיק מסגרות וכוחות; `ai_decision` מקבל החלטות בתוך העולם; `temporal_world` מחזיק את תנאי העוגנים; `runtime_core` מריץ את התבנית. אף אחד מהם אינו כותב לבדו "תסריט קרב" שחוזה כל צעד של השחקן.

| משפחת תבנית | חלקים משותפים | פעילות שחקן אפשרית |
|---|---|---|
| סיור ותצפית | מסלול/אזור, מידע חסר, קשר, גילוי, חזרה | לזהות, לנווט, להעביר תצפית, לבחור מתי להמשיך |
| הגנה והחזקה | עמדות, משמרות, עתודה, לחץ משתנה, אספקה | להתכונן, להכיר את היחידה, לתחזק, להעביר פקודה |
| התקפה על יעד | התכנסות, תנועה, מכשולים, שלבי יעד, שינוי פקודות | לנוע עם היחידה ולפתור בעיה מקומית |
| היתקלות/מארב | תנאי מגע, הפתעה, חוסר ודאות, תגובת כוחות | להבין מה קורה, לתקשר, לסייע ולהיחלץ |
| לחימה בשטח בנוי | חדרים/פתחים, הסתרה, מסלולים, מבנים ושייכות ליחידה | להתמצא ולעבור בין מחסות/אנשים בלי omniscience |
| חציית מכשול/נהר | תורים, מעבר מוגבל, הנדסה, תנועה, אספקה | הכנה, סיוע למעבר ופתרון עיכובים |
| נחיתה אמפיבית | כלי שיט, ים, העמסה/פריקה, חוף, פקודות | פעילות צוות ומעבר בין פלטפורמות; הרחבה עתידית |
| שיירה/ליווי | כלי רכב, פערים בטור, עצירות, תקלה, שינוי ציר | נהיגה, תחזוקה, קשר ושמירה |
| נסיגה/פינוי | סדרי עדיפויות, פצועים, תנועה, מידע מאוחר | לעזור לאנשים ולנהל אובדן מקומי |
| מחנה/שהייה ארוכה | שגרה, שינה, אוכל, אימון, מכתבים, יחסים, שמירות | לחיות כחלק מהיחידה גם בלי קרב |

תבנית מורכבת מ־`Objective`, `Condition/Trigger`, `ForceRole`, `Deployment`, `Phase`, `AnchorPolicy`, `Outcome`, `ExperienceProfile` ו־`Activity`. תנאים הם שפה הצהרתית מוגבלת, גרסתית וניתנת לבדיקה; אין `eval`, קוד שרירותי או קובץ סקריפט ייחודי לאפיזודה. סוגים חדשים של תנאי/פעולה נכנסים לקטלוג דרך בעלים.

עוגן היסטורי אינו מתיר טלפורט של השחקן או החייאת NPC כדי "להחזיר את הסיפור למסלול". לפני פרסום האפיזודה בודקים שמרחב הפעולות המוצע יכול להתקיים בתוך מעטפת העוגנים. כשל התאמה מחייב שינוי scope/תבנית או ענף תוצאה מקומי מוצהר. דמויות, מלאי ופציעות נשמרים גם כשאירוע גדול ממשיך כמתועד.

## 6. מזג אוויר וקרקע — מצב עולם אחד, כמה צרכנים

בעל מזג האוויר הוא `weather_system`. בעל מצב הקרקע הוא `terrain_world`. הקרקע מגיבה לגשם לאורך זמן; הרכב צורך את מצב הקרקע; מערכת הראייה צורכת ראות; renderer מציג את אותם תנאים.

| רכיב | נתונים/התנהגות | השפעה בעולם | הצגה |
|---|---|---|---|
| ציר זמן ומרחב של מזג אוויר | דגימות, תוקף, מקור/שחזור ואינטרפולציה מותרת | השינויים ממשיכים גם ללא מבט שחקן | מעבר הדרגתי ללא מזג אוויר שונה בכל מצלמה |
| גשם/שלג | סוג, עוצמה, הצטברות/המסה לפי fidelity | רטיבות, תנועה, תנאי ראות וחיי יחידה | חלקיקים, משטח רטוב, קול, לבוש |
| רוח | כיוון ועוצמה בדגימה | צרכנים מוצהרים: עשן, ים, פרופיל סימולציה | צמחייה, בד, אבק וקול |
| ערפל/ראות/עננות | מצב וגבול טווח תקף | תפיסה וניווט מתוך מידע מוגבל | תאורה, ערפל וצל; אין "NPC רואה דרך הערפל" |
| טמפרטורה ומצב סביבה | ערכים/טווחים ואי־ודאות | עייפות/שהייה/ציוד אם ממומש | נשימה, ביגוד וקול רק כשמתאים |
| בוץ/שלג/קרח/רטיבות בקרקע | מצב מתמשך ותכונות חומר | החלקה, מעבר, עקבות ורכב שנתקע | material ו־decals תואמים |
| ים וגלים | מתאם ימי בבעלות naval | תנועת כלי שיט, העמסה ופריקה | פני מים וקול; מחוץ לפרוסה הראשונה |
| שמש/שעה | זמן ומיקום מפורשים | שגרות ותאורה; זמן אינו מזג אוויר | lighting/sky לפי אותו שעון |

אם ידוע שהיה גשום אך אין סדרת מדידות, נשמרת עובדת הגשם בנפרד מתזמון סינתטי משוחזר. תקציב גדול יכול לשפר ראיות, סימולציה ותצוגה בשלוש עבודות שונות. פרופיל Easy יכול לשפר ניווט וסלחנות; אין צורך לשנות את זהות מזג האוויר ההיסטורי.

## 7. איך מציגים את הלגו ואת המשחק

יש שני צרכנים שונים לאותו manifest: כלי הפיתוח והשחקן בעולם.

**כלי קטלוג למפתחים — מפרט למסך עתידי:** עץ משמאל: תחום ← משפחה ← טיפוס ← דגם ← גרסה. במרכז תצוגת 3D/סצנת בדיקה. מימין זהות הדגם, בעלים, חלקים, תלויות, מקורות, פערים, תמיכה ב־desktop/VR ורמות פירוט. פילטרים: מוכן/חסר/בבדיקה, תקופה, תיאטרון, משפחה, איכות, רישיון וביצועים. שמות וריאנטים לא מאומתים מוצגים כ־candidate.

בטנק בוחרים פירוק לרכיבים, תנועת צריח/זחל, collision, עמדות צוות ו־LOD. בנשק בודקים אחיזה/טעינה ותאימות תחמושת. במזג אוויר מזיזים זמן ותנאים ובודקים יחד תצוגה ותוצאה סימולטיבית. בתבנית קרב מציגים שלבים, מטרות וכוחות, ואז מריצים sandbox. מצב זה הוא כלי בדיקה; הוא אינו החוויה שהשחקן נדרש לעבור.

**בתוך המשחק:** הטנק נמצא בדרך, זז ונשמע; חייל מוכר מבקש עזרה; הגשם מצטבר; הטור נעצר; הפקודה מגיעה באיחור. המידע מגיע דרך אנשים, ציוד, סביבה ואינטראקציות. inspector היסטורי הוא אופציונלי. אין חובה להציג שם רכיב, graph או מספר confidence על המסך הרגיל.

**חוזה התצוגה:** SimState → PlayerProjection → PresentationState → mesh/animation/audio/UI. `PlayerAction` חוזר בכיוון ההפוך ועובר ולידציה. renderer אינו כותב תחמושת, נזק או מזג אוויר. החלפת LOD חזותי אינה מוחקת אדם; שינוי LOD סימולטיבי משמר זהות, משאבים ותוצאות.

**הכנה ל־VR כעת:** יחידות מטריות עקביות; גוף/ראש/ידיים נפרדים; נקודות אחיזה/ישיבה/כניסה; colliders סבירים; UI קריא במרחב; מיפוי פעולות ללא תלות בעכבר; pause/ישיבה/נגישות. M1 מוכיח משחק desktop וגבולות קלט/מצלמה באמצעות fixtures; בדיקת headset מוקדמת מומלצת אם המכשיר זמין. נוחות, locomotion, כוונה בשתי ידיים ופנים רכב חייבים בדיקה על מכשיר לפני הכרזת תמיכת VR, ואינם מוכחים על ידי mock. OpenXR אינו הופך לבד משחק desktop למשחק VR. היעד provisional הוא Godot + OpenXR; ביצועים ו־PCVR לעומת standalone דורשים מדידה לפי [VR_READINESS](VR_READINESS.md).

## 8. עץ הסוכנים והאחריות

```text
Astra Root — backlog, בעלויות, חוזים, שילוב והחלטות
├── חוקר היסטוריה — מקורות, טענות ודגמים (Opus/Astra)
├── עולם — terrain_world, temporal_world, weather_system
├── ציוד — ground_platform, ground_powertrain, weapons_ballistics, weapons_damage
├── חיים ביחידה — infantry, characters, command, logistics, AI
├── חוויה ונכסים — experience_loop, experience_interface, visual, motion, audio
├── Runtime — runtime_core, runtime_continuity, context_router, economy_provider
└── ביקורת עצמאית — היסטוריה, provenance, סימולציה, שילוב וחוויה
```

זהו עץ אחריות. סדר הביצוע הוא גרף תלויות, ואינו שרשרת סוכנים קשיחה. תעופה וצי הם בעלי תחום רשומים שמופעלים רק כשיש צורך. גם בתוך תחום אין חובה להפעיל מנהל ביניים. כרגע יש ארבעה מקומות ריצה בכל העץ: root ועוד שלושה עובדים. 31 ההתמחויות בקטלוג הן כתובות אחריות, לא 31 תהליכים רצים.

לכל קובץ/רכיב יש כותב אחד. סוכן שני יכול לחקור או לבדוק, אך אינו עורכו במקביל. שינוי חוזה משותף עובר ב־B00 עם גרסת migration; שינוי חוצה תחומים נשלח כביקשת שינוי לבעלים. סוכני פיתוח אינם NPCs; אין צורך להפעיל LLM לכל חייל או בכל tick.

## 9. איזה מודל לכל סוג משימה

| פרופיל בקטלוג | ברירת מחדל | חלופה | מה הוא מקבל |
|---|---|---|---|
| ORCHESTRATE | Astra high/xhigh | Opus 5.5 high | אינדקס בעלויות, מצב עבודה והחלטות פתוחות |
| DEEP | Astra high | Opus 5.5 high | בעיה מוגדרת, חוזים, fixtures והנחות; max רק להסלמה ממוקדת |
| IMPLEMENT | Sol 6 high | Sonnet 5 high; בסביבה זו Sol 5.6 high | מודול אחד, API תלוי ובדיקות רלוונטיות |
| RESEARCH | Opus 5.5 high | Astra high | רשימת שדות לחקור, מקור/קטע מדויק, scope של דגם/זמן/מקום |
| DESIGN | Sonnet 5 high | Sol 6 high; כאן Sol 5.6 high | תפקיד שחקן, פעולות, מגבלות היסטוריות וקריטריוני חוויה |
| VISUAL | Sol 6 high לכלי הייצור | Sonnet 5 high לעיצוב וביקורת | reference board מורשה, מידות, VariantId ותקציבי asset |
| EXTRACT | parser תחילה; Luna 6 low כשצריך מודל | Haiku 4.5; כאן Luna 5.6 low | קטע קצר וסכמה; ולידציה עצמאית לפני שימוש |
| REVIEW | Opus 5.5 high לתוצר Codex | Astra high לתוצר Claude/ביקורת כאן | requirements + diff + evidence + תוצאות בפועל |

אלו מסלולי ברירת מחדל. למשל `ground_platform` משתמש ב־IMPLEMENT לכתיבת מכלול; הכרעה חדשה ב־LOD או בחוזה נזק היא משימת DEEP נפרדת. לא שולחים כל גלגל ל־Astra max. ל־Haiku 4.5 לא שולחים שדה effort שאינו נתמך. הסקת עובדות ממודל אינה תחליף לעיון במקור. ביקורת של ספק אחר מסייעת לגיוון, אך אינה הוכחת אמת או חוויה טובה.

המודלים והשמות נבדקו בתיעוד הרשמי: [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [Sol](https://developers.openai.com/api/docs/models/gpt-6-sol), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [מודלי Codex](https://learn.chatgpt.com/docs/models), [Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview), [Sonnet 5](https://platform.claude.com/docs/en/models/sonnet-5/overview), [Haiku 4.5](https://platform.claude.com/docs/en/models/haiku-4-5/overview), [Claude effort](https://platform.claude.com/docs/en/build-with-claude/effort). זמינות בחשבון היא בדיקה נפרדת; לא בוצעה כאן הרצת Claude או העברת משימות בתשלום. פירוט אסמכתאות: [OpenAI](planning/OPENAI_MODEL_RESEARCH.md), [Claude](planning/CLAUDE_MODEL_RESEARCH.md).

## 10. בדיוק איזה קונטקסט לשלוח

כל חבילת עבודה מתחילה בקובץ `context/game/build_packets/Bxx/BRIEF.md`. משם בוחרים **קבצים ספציפיים**, לא מצרפים תיקייה שלמה:

1. `context/game/global/INVARIANTS.md` — העקרונות הקצרים המשותפים.
2. `context/game/domains/<domain>/DOMAIN.md` ו־`roles/<owner>.md` — התחום, הבעלות והפניות לרכיבים שהוקצו.
3. TaskSlice — תת־קבוצת IDs, תוצאה רצויה, קובצי קוד רלוונטיים, read/write allowlist ובדיקות.
4. DependencyInterfaces — רק החוזים הנצרכים, עם גרסה/hash ו־fixture; שם ממשק ברשימה עדיין אינו חוזה ממומש.
5. EvidenceSlice — רק הראיות לאותו דגם/זמן/מקום, עם locator, provenance ורישיון. synthetic fixtures מסומנים בנפרד.

סוכן הטנק אינו מקבל את כל הצי, התעופה או ארכיון מלחמת העולם. סוכן mesh אינו זקוק למימוש solver נזק. חוקר דגם מקבל את סכמת השדות ואת המקורות; הוא אינו זקוק למימוש renderer. סוכן ההרכבה מקבל envelopes ומניפסטים של יכולות, ומרחיב רק כדי לפתור בעיה קונקרטית.

תקציבי פתיחה מומלצים, שאינם מגבלות המודלים: 6–12k tokens למימוש ממוקד, 12–24k לחוזה מורכב, 8–16k למחקר, 2–6k לחילוץ, 16–32k לשורש. אם מידע מחייב לא נכנס, מפצלים משימה או מבקשים הרחבה מתועדת; לא משמיטים יחידות, ראיות או חוזה כדי לעמוד בתקציב. המערכת הקיימת ב־M0 בוחרת הפניות; היא אינה sandbox לקבצים או materializer מלא. תיקיות ההקשר שנוצרו כאן הן חבילות תכנון, לא אכיפת הרשאות.

## 11. מה חייב לחזור מכל בניית לגו

| תוצר | תוכן מחייב |
|---|---|
| manifest | LegoId, version, owner, interfaces/dependencies, supported profiles, hashes |
| הגדרה/מימוש | פרמטרים ותנהגות כללית; קוד רק כאשר הנתונים אינם מספיקים |
| evidence mapping | מקור ברמת שדה, תחולת דגם, אי־ודאות, שחזור וחוסרים |
| נכסים | רישיון, קנה מידה, צירים, VariantId, sockets, LOD; או gap מפורש |
| test scene | דוגמה סינתטית קטנה להפעלה/תצוגה, ללא תלות באפיזודה אחת |
| בדיקות | חוזים, מקרי כשל, שימוש חוזר, שמירה, התאמת דגם, עלות ביצועים לפי הצורך |
| handoff | מה השתנה, מה לא נבדק, context ששימש, פערים, פקודת הרצה ותוצאות אמיתיות |

מפרידים מצבי קבלה: `code_ready`, `historical_reviewed`, `visual_reviewed`, `experience_reviewed`, `device_tested`. אלה דגלי תכנון מוצעים שיוגדרו בסכמה, ולא החלפה של סטטוס תוצאת Deliver. `code_ready` אינו הופך את שאר הדגלים ל־true. לא מפרסמים Episode לפני שערי historical/provenance/simulation/integration ו־ExperienceReview; VR מחייב שער מכשיר נפרד כשמשחררים יעד VR.

## 12. סדר בנייה ללא מפעל ענק מראש

| גל | עד שלושה עובדים לצד root | מה נבדק לפני הגל הבא |
|---|---|---|
| 0 | B00 חוזים; B03 מחקר דגם ראשון; B07 מיפוי נכסים קיימים ורישיונות | ממשקים נבחרים נעולים; פערי ראיות/כלים גלויים |
| 1 | B01 רכב; B02 נשק; B04 עולם/מזג אוויר | שלוש סצנות קטנות מתחברות לאותו host ומשתמשות באותם חוזים |
| 2 | B06 אנשים; B05 תבנית פעילות; B08 גוף/קלט/תצוגה | יש תפקיד, פעולה שקטה, חבר מוכר והחלטה מקומית |
| 3 | B07 חיבור נכסים; B09 שילוב ושמירה; ביקורת עצמאית | יכולות עובדות יחד, מגבלות מתועדות, playtest אנושי |
| 4 | דגם שני/תבנית שנייה על אותו loader | נתוני אפיזודה/דגם חדשים אינם דורשים fork של המנוע |

כל גל מוגבל לשלושה עובדים בפועל: חבילה מרובת בעלים מתפצלת למשימות שממתינות בתור או רצות בזמנים שונים, ולא לשלושה עצים שכל אחד מפעיל עובדים נוספים.

בין גל 0 לגל 1 משבצים את `B09/continuity_seam`. עיצוב B05 יכול להקדים את גל 2: הוא מספק נתונים למשימת ההמשך של B00, ואינו ממתין למימוש evaluator. `B09/final_integration` מתחיל רק אחרי חיבור המודולים. גרף משימות מפורט מופיע במרשם תחת `dispatch_tasks`; הוא תכנון הרצה, לא מתזמן פעיל.

סדר זה מפרט את העבודה בתוך [IMPLEMENTATION_SEQUENCE](IMPLEMENTATION_SEQUENCE.md): M1 הוא spike טכני וחווייתי; M2 מחקר/preflight; M3 פרוסה היסטורית ראשונה; M4 אפיזודה שנייה; M5 עומק והתמדה; M6 מתאם Deliver אמיתי. רכיבי אוויר/ים מורכבים מסומנים FUTURE ומוזמנים רק כשאפיזודה מחייבת אותם. ב־M1 מגדירים חומרת desktop וניסוי VR מתוכנן; בחירת יעד VR והוכחת מכשיר הן gate להבטחת תמיכה בו. מכשיר שאינו זמין נרשם כסיכון פתוח ואינו מוכיח תאימות; אין צורך לעכב בגללו את כל בניית ה־desktop.

העבודה הראשונה המומלצת היא B00, B03 וסקירת הנכסים מתוך B07. מיד לאחר הקפאת החוזים אפשר לתת ל־Codex את הטנק, הנשק ומזג האוויר במקביל. אין צורך לבנות עשרה דגמי טנקים לפני שהדגם הראשון מהנה ומשתלב.

<!-- GENERATED_CATALOG_START -->
## 13. רישום מלא: 158 טיפוסי לגו

הרשימה היא של טיפוסים, לא של כל דגם היסטורי ולא של כל מופע בעולם. `primitive` הוא חלק/הגדרה; `capability` היא התנהגות; `assembly` היא הרכבה; `service` הוא שירות בנייה/בדיקה/מדיניות. לא כל שורה היא תהליך או entity נפרד.

השלב מציין צורך/קבלה ראשונה מתוכננת: M2 לשדות מחקר והגדרות, M3 לתוכן ומימוש הפרוסה שנבחרה; fixtures עשויים להתחיל ב־M1. אין דרישה לממש כל שורת M3 בפרוסה הראשונה. M4 בודק שימוש חוזר באפיזודה שנייה; M5 עומק והתמדה; M6 מתאם Deliver; FUTURE לפי צורך. נתיבי התוצר הם **יעדי כתיבה עתידיים**, לא דיווח על קבצים קיימים.

הפרופיל בכל שורה נפתר למודל ולחלופה בטבלת סעיף 9 ובמרשם JSON. תיקיית הקונטקסט נגזרת מהתחום; כרטיס הכותב המדויק מופיע בסעיף 14. חבילת השיגור בוחרת רק את הרכיבים הנדרשים מתוך הרשימה.

### רכב וטנקים — 16 טיפוסים

קונטקסט: `context/game/domains/ground_vehicles/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `equipment.engine` (primitive) | ליבת מנוע משותפת: אספקת הספק לציר, צריכת משאב ומצב תקינות; פרמטרים לפי וריאנט. | `ground_powertrain` · IMPLEMENT · M2 | `Units`, `ResourceAccount`, `VariantEvidence` | אותו חוזה מקבל מנוע קרקעי ונתוני מתאם מאושרים; אינו ממציא עקומת ביצועים למטוס או אונייה. | `capabilities/ground_vehicles/primitives/engine/` |
| `equipment.transmission` (primitive) | יחסי העברה וכיוון בין מקור הספק להינע במודל מוצהר. | `ground_powertrain` · IMPLEMENT · M2 | `ShaftPower`, `VariantEvidence` | הילוך, כיוון ואובדן הספק נרשמים; יחס חסר אינו מוצג כנתון היסטורי. | `capabilities/ground_vehicles/primitives/transmission/` |
| `equipment.wheel` (primitive) | גלגל בעל מידה, חומר ומגע המשמש כלי רכב ויישומים נוספים. | `ground_powertrain` · IMPLEMENT · M2 | `SurfaceMaterial`, `ContactSample`, `VariantEvidence` | הרדיוס במטרים תואם גאומטריה; החלקה וקירוב מגע מתועדים לפי רמת פירוט. | `capabilities/ground_vehicles/primitives/wheel/` |
| `equipment.track` (primitive) | זחל עם תחום מגע, מצב תקינות וממשק העברת כוח. | `ground_powertrain` · IMPLEMENT · M2 | `SurfaceMaterial`, `ContactSample`, `VariantEvidence` | זחל פגוע משנה ניידות; כמות חוליות חזותית אינה מגדירה לבדה את מודל התנועה. | `capabilities/ground_vehicles/primitives/track/` |
| `equipment.suspension` (primitive) | מענה עומס ומגע של מתלה עבור הרכב שנבחר. | `ground_powertrain` · IMPLEMENT · M2 | `ContactSample`, `MassProperties`, `VariantEvidence` | נסיעה על מדרגה נשארת בתחום היציבות שנבדק; קירוב קשיח מסומן אם אין מודל מפורט. | `capabilities/ground_vehicles/primitives/suspension/` |
| `mobility.tracked` (capability) | תנועה קרקעית באמצעות זוג זחלים או תצורה מאושרת אחרת. | `ground_powertrain` · IMPLEMENT · M3 | `TerrainSample`, `MobilityEnvelope`, `ShaftPower`, `TrackState`, `AcceptedPhysicsOutcome`, `SurfaceState` | פנייה, שיפוע, דלק וזחל פגוע משנים תוצאה עקבית; עמידה או LOD אינם יוצרים מרחק חינם. | `game/runtime/ground_vehicles/tracked_mobility/` |
| `mobility.wheeled` (capability) | תנועה קרקעית גלגלית לפי אחיזה, עומס ומעטפת כלי הרכב. | `ground_powertrain` · IMPLEMENT · M3 | `TerrainSample`, `MobilityEnvelope`, `ShaftPower`, `WheelState`, `AcceptedPhysicsOutcome`, `SurfaceState` | עומס ודלק מחויבים; תוואי לא עביר אינו נעשה עביר עקב מסלול אנימציה. | `game/runtime/ground_vehicles/wheeled_mobility/` |
| `equipment.chassis` (primitive) | שלדה עם מסה, מידות ונקודות חיבור למרכיבי הרכב. | `ground_platform` · IMPLEMENT · M2 | `MassProperties`, `VariantEvidence` | מסה ומידות נושאות מקור ויחידות; חיבורים מזהים רכיבים במפורש ולא לפי שמות mesh. | `capabilities/ground_vehicles/primitives/chassis/` |
| `equipment.armor_plate` (primitive) | לוח מיגון בעל גאומטריה, חומר ועובי לפי מקור או קירוב מוצהר. | `ground_platform` · IMPLEMENT · M2 | `SurfaceMaterial`, `VariantEvidence`, `CoordinateTransform` | זווית ועובי נשמרים ביחידות תקינות; תוצאת חדירה שייכת ל־weapons_effects ולא ללוח עצמו. | `capabilities/ground_vehicles/primitives/armor_plate/` |
| `equipment.turret` (assembly) | צריח עם טבעת חיבור, מגבלות צידוד והגבהה, תושבות ועמדות צוות. | `ground_platform` · IMPLEMENT · M2 | `WeaponMount`, `ArmorGeometry`, `CrewStation`, `VariantEvidence` | תותח אינו מכוון מעבר למגבלה; צריח מושבת אינו מוצג כפועל. | `capabilities/ground_vehicles/assemblies/turret/` |
| `equipment.fuel_tank` (primitive) | מכל דלק עם קיבולת, סוג חומר, מיקום ומצב דליפה. | `ground_platform` · IMPLEMENT · M2 | `ResourceAccount`, `FuelCompatibility`, `VariantEvidence` | אין תדלוק מעל קיבולת או בחומר בלתי תואם; דליפה עוברת דרך ledger ולא מעלימה מלאי. | `capabilities/ground_vehicles/primitives/fuel_tank/` |
| `equipment.crew_station` (primitive) | עמדת נהג, תותחן או איש צוות עם תפוסה, גישה ושדה עבודה. כולל קישור לפתח, נקודות כניסה/יציאה, מבט, ישיבה, אחיזה וגישה פנימית. | `ground_platform` · IMPLEMENT · M2 | `ActorIdentity`, `InteractionAffordance`, `VariantEvidence` | תפקיד ותפוסה מקנים רק פעולות מורשות; שינוי מצלמה אינו ממלא עמדה ריקה. | `capabilities/ground_vehicles/primitives/crew_station/` |
| `equipment.ground_vehicle` (assembly) | הרכבת וריאנט ו־instance של טנק, משאית או רכב אחר מרכיבים נעולים. | `ground_platform` · IMPLEMENT · M2 | `VariantEvidence`, `MobilityEnvelope`, `WeaponMount`, `ArmorGeometry`, `CrewStation`, `ResourceAccount`, `AssetBinding` | זהות חזותית, ציוד, צוות ונזק מסכימים; כשל מנוע/נשק נשמר בלי health כללי יחיד. | `capabilities/ground_vehicles/assemblies/ground_vehicle/` |
| `equipment.access_port` (primitive) | פתח/דלת/מדף של כלי רכב עם מצב, תנאי גישה ונקודות כניסה/יציאה. | `ground_platform` · IMPLEMENT · M3 | `CrewStation`, `InteractionAffordance`, `AttachmentBinding` | מעבר בין חוץ לפנים שומר אדם יחיד ותפוסה; דלת סגורה אינה מעבר; grip/seat במטרים. | `capabilities/ground_vehicles/equipment/access_port/` |
| `equipment.stowage` (primitive) | מכל אחסון דלק, תחמושת או מטען עם קיבולת, משקל וגישה. | `ground_platform` · IMPLEMENT · M3 | `ResourceAccount`, `SupplyTransfer`, `VariantEvidence` | העברה אטומית; container בעל סמכות אחת; אין שכפול מלאי בהעברת רכב או שמירה. | `capabilities/ground_vehicles/equipment/stowage/` |
| `mobility.hybrid` (capability) | הרכבת ניידות גלגלים וזחלים לרכב חצי־זחלי בלי fork נפרד של מנוע. | `ground_powertrain` · IMPLEMENT · FUTURE | `WheelContact`, `TrackContact`, `MobilityCommand`, `TerrainSample` | תצורת מגע מוצהרת; fixture משותף בודק פניות/אחיזה ללא תלות בשם דגם. | `capabilities/ground_vehicles/mobility/hybrid/` |

### נשק, תחמושת ואפקטים — 18 טיפוסים

קונטקסט: `context/game/domains/weapons_effects/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `equipment.gun` (assembly) | הגדרת כלי ירייה עם קנה, תושבת, הזנה ומאפייני וריאנט. | `weapons_ballistics` · IMPLEMENT · M2 | `VariantEvidence`, `WeaponMount`, `AmmunitionCompatibility`, `BarrelDefinition`, `BreechDefinition`, `FeedDefinition`, `StockDefinition`, `WeaponActionDefinition` | שני מתכוני דגם נטענים באותו loader; קנה/בית בליעה/הזנה/תחמושת או נכס לא תואמים נדחים; אין המצאת נתונים בגלל mesh דומה. | `capabilities/weapons_effects/assemblies/gun/` |
| `equipment.projectile` (primitive) | קליע או פגז עם מסה, ממדים, סוג ופרמטרי השפעה מבוססים. | `weapons_ballistics` · IMPLEMENT · M2 | `VariantEvidence`, `Units`, `SurfaceMaterial` | טיפוס, וריאנט ויחידות נשמרים; מקור חלקי אינו מאשר טבלת חדירה מלאה. | `capabilities/weapons_effects/primitives/projectile/` |
| `equipment.optic` (primitive) | כוונת או מכשיר אופטי עם מגבלות שדה ראייה, הגדלה ויישור. | `weapons_ballistics` · IMPLEMENT · M2 | `VariantEvidence`, `SensorEnvelope`, `WeaponMount` | המצלמה מציגה רק מידע שנצפה דרך מעטפת מאושרת; הגדלה אינה חושפת אויב נסתר. | `capabilities/weapons_effects/primitives/optic/` |
| `weapons.ammunition_compatibility` (service) | התאמת תחמושת, מטען, הזנה ותושבת לווריאנט נשק. | `weapons_ballistics` · IMPLEMENT · M2 | `GunDefinition`, `ProjectileDefinition`, `VariantEvidence` | קוטר זהה בלבד אינו מספיק; אי־התאמה או חוסר מידע מפיקים שגיאה מפורשת. | `capabilities/weapons_effects/ammunition_compatibility/` |
| `weapons.firing_reload` (capability) | מצב טעינה, ירי, טעינה מחדש והפרעה לפעולה של נשק קטן או תותח. | `weapons_ballistics` · IMPLEMENT · M3 | `AmmunitionCompatibility`, `InventoryTransfer`, `ActorAction`, `WeaponMount` | ירייה מחייבת מלאי ומצב תקין; reload שהופרע אינו מסתיים בגלל אנימציה. | `game/runtime/weapons_effects/firing_reload/` |
| `weapons.ballistics` (capability) | מסלול קליע ופתרון פגיעה בתחום מרחק ומהירות שהמודל תומך בו. | `weapons_ballistics` · IMPLEMENT · M3 | `ShotRequest`, `WeatherSample`, `CollisionQuery`, `ProjectileDefinition` | אותו קלט נותן תוצאה בתחום determinism המוצהר; מעבר לטווח התקפות מחזיר unsupported. | `game/runtime/weapons_effects/ballistics/` |
| `effects.armor_interaction` (capability) | השפעת פגיעה על לוח וחלק פנימי לפי תחמושת, זווית ומודל מוצהר. | `weapons_damage` · DEEP · M3 | `ShotImpact`, `ArmorGeometry`, `SurfaceMaterial`, `ProjectileDefinition` | חדירה, אי־חדירה או unknown ניתנים לבדיקה; אין דיוק מספרי ללא בסיס וכיול. | `game/runtime/weapons_effects/armor_interaction/` |
| `effects.blast` (capability) | השפעת הדף ורסיסים במעטפת מקומית עם כיסוי ומגבלות קירוב. | `weapons_damage` · DEEP · FUTURE | `ExplosionRequest`, `CollisionQuery`, `SurfaceMaterial`, `DamageTarget` | כיסוי ומרחק משנים השפעה בתוך המודל; אירוע יחיד אינו מוחל פעמיים. | `game/runtime/weapons_effects/blast/` |
| `effects.fire` (capability) | הצתה, בעירה ודעיכה בתחומים נתמכים עם צריכת חומר ונזק מוצהר. | `weapons_damage` · DEEP · M3 | `FuelState`, `SurfaceMaterial`, `WeatherSample`, `DamageTarget`, `ResourceAccount` | בעירה אינה יוצרת דלק; מעבר LOD שומר תוצאה וחומר נצרך ומסמן קירובים. | `game/runtime/weapons_effects/fire/` |
| `effects.suppression` (capability) | המרת אש קרובה וגירויים מאושרים לאירוע דיכוי זמני של פעילות. | `weapons_damage` · DEEP · M3 | `ShotTrace`, `ActorObservation`, `SuppressionPolicy` | אש קרובה יכולה להפריע בלי ליצור פציעה; אירוע נגזר מחשיפה מורשית ולא מידע אויב נסתר. | `game/runtime/weapons_effects/suppression/` |
| `equipment.barrel` (primitive) | קנה נשק בעל אורך, קדח, מסה ונקודות חיבור לפי וריאנט. | `weapons_ballistics` · IMPLEMENT · M2 | `VariantEvidence`, `WeaponMount`, `AmmunitionCompatibility`, `AttachmentBinding` | אורך וקליבר תואמים ההגדרה והחזות; קנה חלופי אינו מקנה ביצועים חדשים ללא מודל מאושר. | `capabilities/weapons_effects/primitives/barrel/` |
| `equipment.breech` (primitive) | מכלול סגירה ותפעול של בית הבליעה, ידני או אוטומטי, לפי תצורה נתונית. | `weapons_ballistics` · IMPLEMENT · M2 | `VariantEvidence`, `WeaponMount`, `AmmunitionCompatibility`, `AttachmentBinding` | רובה בריח ורובה בטעינה עצמית בוחרים state model נתמך; נתון לא ידוע נשאר חוסר. | `capabilities/weapons_effects/primitives/breech/` |
| `equipment.feed_system` (primitive) | מחסנית, חגורה או הזנה אחרת עם קיבולת, תאימות ומצב נוכחי. | `weapons_ballistics` · IMPLEMENT · M2 | `VariantEvidence`, `WeaponMount`, `AmmunitionCompatibility`, `AttachmentBinding` | תחמושת מחויבת מחשבון מלאי אחד; החלפת מחסנית אינה משכפלת יתרה וציוד לא תואם נדחה. | `capabilities/weapons_effects/primitives/feed_system/` |
| `equipment.weapon_stock` (primitive) | קת ומשטחי אחיזה הנקשרים למעטפת נשק ול־anchors אנושיים. | `weapons_ballistics` · IMPLEMENT · M2 | `VariantEvidence`, `WeaponMount`, `AmmunitionCompatibility`, `AttachmentBinding` | גרסה, מידות ואחיזה תואמים מקור או שחזור; hand IK מציג את האחיזה ואינו משנה בליסטיקה. | `capabilities/weapons_effects/primitives/weapon_stock/` |
| `equipment.weapon_action` (primitive) | הגדרת משפחת מנגנון בריחי/ידני, חצי־אוטומטי או אוטומטי ופעולותיו. | `weapons_ballistics` · IMPLEMENT · M2 | `FeedDefinition`, `AmmunitionCompatibility`, `WeaponAction` | מעברים לא חוקיים נדחים; מצב טעינה נשמר; כל ירייה צורכת משאב פעם אחת. | `capabilities/weapons_effects/equipment/weapon_action/` |
| `equipment.weapon_mount` (primitive) | הגדרת חיבור נשק מקומי לאחיזה, חצובה או פלטפורמה. platform מחזיק transform עולמי ומצב צירי צריח; הנשק צורך אותם. | `weapons_ballistics` · IMPLEMENT · M2 | `MountTransform`, `VariantEvidence`, `GripAnchor` | אותו מכלול נשק צורך mount contract; שינוי פלטפורמה אינו מעתיק קוד ירי. | `capabilities/weapons_effects/equipment/weapon_mount/` |
| `equipment.throwable` (assembly) | פריט משחק נזרק המורכב מפעולה, מטען, תנועה ואפקט; ללא פרטי בנייה בעולם האמיתי. | `weapons_ballistics` · IMPLEMENT · FUTURE | `WeaponAction`, `ProjectileDefinition`, `DamageEffect` | אירוע אחד, בעלות מלאי וזהות נשמרים; תצורה לא תואמת נדחית. | `capabilities/weapons_effects/equipment/throwable/` |
| `effects.obscurant` (capability) | נפח עשן/אבק שמשפיע על ראות לאורך זמן ומפיק מצב להצגה. | `weapons_damage` · DEEP · M3 | `WeatherSample`, `VisibilityEnvelope`, `AcceptedEvent` | AI ו־renderer צורכים אותו נפח/צפיפות בגבולות fidelity מוצהרים; אין עשן קוסמטי שמסתיר רק מהשחקן. | `capabilities/weapons_effects/effects/obscurant/` |

### מזג אוויר — 7 טיפוסים

קונטקסט: `context/game/domains/weather/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `weather.sample` (primitive) | מצב מקומי מתוארך של רוח, משקעים, טמפרטורה וראות עם אי־ודאות. | `weather_system` · IMPLEMENT · M2 | `EvidenceSnapshot`, `TemporalApplicability`, `CoordinateTransform` | מזג אוויר שלא תועד מוצג כשחזור; זמן ומקום שאינם תואמים נדחים. | `capabilities/weather/samples/` |
| `weather.effects` (capability) | הפקת modifiers מוגבלים של ראות, קול וחשיפה עקב מזג האוויר; אין כתיבה ישירה למצב השייך לקרקע, לאדם או ל־renderer. | `weather_system` · IMPLEMENT · M3 | `WeatherSample`, `SurfaceMaterial`, `VisibilityEnvelope`, `AcousticEnvelope` | הצרכנים מחילים modifiers פעם אחת; תצוגה ותפיסה מקבלות אותה דגימה; שינוי רטיבות נשמר בבעלות terrain_world. | `game/runtime/weather/effects/` |
| `weather.timeline` (assembly) | סדרת תנאים מרחבית/מתוארכת עם מדיניות אינטרפולציה והפרדת מקור משחזור. | `weather_system` · IMPLEMENT · M3 | `WeatherSample`, `TemporalApplicability`, `CoordinateTransform` | מעבר זמן ושמירה נותנים אותה דגימה; יצירת רצף מנתון יחיד מסומנת כשחזור. | `capabilities/weather/weather/timeline/` |
| `weather.precipitation` (primitive) | הגדרת משקעים: גשם/שלג/ללא משקעים, עוצמה וטווח אי־ודאות. | `weather_system` · IMPLEMENT · M2 | `WeatherSample`, `VariantEvidence` | מצב לא ידוע אינו שמיים בהירים; הצטברות קרקע נעשית אצל terrain_world. | `capabilities/weather/weather/precipitation/` |
| `weather.wind` (primitive) | שדה רוח או דגימה מקומית עם יחידות, כיוון ושיטת קירוב. | `weather_system` · IMPLEMENT · M2 | `WeatherSample`, `CoordinateTransform` | עשן, קול ופני מים מקבלים אותה מסגרת צירים וזמן; gaps נשמרים. | `capabilities/weather/weather/wind/` |
| `weather.visibility_cloud` (primitive) | עננות, ערפל ומעטפת ראות שאינם תלויים במצלמה. | `weather_system` · IMPLEMENT · M2 | `WeatherSample`, `VisibilityEnvelope` | תצוגה ו־perception משתמשות באותה דגימה; profile חזותי זול לא מעניק ידיעה עודפת ל־AI. | `capabilities/weather/weather/visibility_cloud/` |
| `weather.thermal` (primitive) | טמפרטורה ולחות כאשר קיימות ראיות או שחזור מוצהר. | `weather_system` · IMPLEMENT · M2 | `WeatherSample`, `EvidenceSnapshot` | השפעת חשיפה מחושבת בידי בעל מצב האדם; לא מומצא נתון מדידה היסטורי. | `capabilities/weather/weather/thermal/` |

### קרקע, מבנים, זמן ועוגנים — 19 טיפוסים

קונטקסט: `context/game/domains/geospatial_temporal/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `world.terrain` (primitive) | תבליט וגאומטריית קרקע מקומית לשימוש בתנועה, תצוגה וכיסוי. | `terrain_world` · IMPLEMENT · M2 | `CoordinateTransform`, `EvidenceSnapshot` | גובה, שיפוע והתנגשות עקביים במטרים; פירוט שאינו נתמך מסומן כשחזור. | `capabilities/geospatial_temporal/terrain/` |
| `world.surface_material` (primitive) | סוג פני שטח המספק חיכוך, התנגדות ותכונות פיזיקליות תחומות. | `terrain_world` · IMPLEMENT · M2 | `EvidenceClaim`, `ReconstructionRecord` | דגימה מספקת יחידות, שיטת קירוב וטווח תקפות; בוץ חזותי ותגובה מכנית אינם סותרים. | `capabilities/geospatial_temporal/surface_materials/` |
| `world.water_body` (primitive) | נהר, אגם או אזור ים עם תחום מים, עומק וגובה ידועים או משוחזרים. | `terrain_world` · IMPLEMENT · M2 | `CoordinateTransform`, `EvidenceSnapshot` | עומק לא ידוע נשאר לא ידוע; חוף, קו מים ומעברי יבשה משתמשים באותה גאומטריה. | `capabilities/geospatial_temporal/water_bodies/` |
| `world.hydrology` (capability) | זרימה, הצפה ועבירות מים במודל מוגבל לסביבה שנבחרה. | `terrain_world` · IMPLEMENT · FUTURE | `WaterBody`, `WeatherSample`, `TerrainSample` | שינוי מפלס מתורגם לעבירות לפי מודל מוצהר; אין טענה לסימולציית נוזלים מלאה. | `capabilities/geospatial_temporal/hydrology/` |
| `world.building` (primitive) | מבנה בעל נפח, פתחים, קומות ותמיכות הנחוצות למשחק. | `terrain_world` · IMPLEMENT · M2 | `TerrainSample`, `SurfaceMaterial`, `EvidenceSnapshot` | פתחים וקומות תואמים התנגשות וניווט; אין שיוך בניין היסטורי ללא ראיה מתאימה. | `capabilities/geospatial_temporal/buildings/` |
| `world.wall` (primitive) | קיר כמקטע גאומטרי בעל חומר, עובי, פתחים וכיסוי. | `terrain_world` · IMPLEMENT · M2 | `SurfaceMaterial`, `CoordinateTransform` | עקבות ראייה, תנועה ופגיעות משתמשים באותו מיקום; עובי חסר אינו מקבל דיוק מומצא. | `capabilities/geospatial_temporal/walls/` |
| `world.bridge` (assembly) | גשר המחבר מקטעי דרך מעל מכשול עם מגבלת מעבר ועומס. | `terrain_world` · IMPLEMENT · M2 | `RoadSegment`, `WaterBody`, `SurfaceMaterial`, `EvidenceClaim` | כלי שאינו עומד במגבלת המעבר נדחה; מקור, קירוב או חוסר של מגבלת עומס גלויים. | `capabilities/geospatial_temporal/bridges/` |
| `world.tree` (primitive) | עץ או צמחייה עם נפח מעבר, הסתרה וזהות סביבתית. | `terrain_world` · IMPLEMENT · M2 | `TerrainSample`, `SurfaceMaterial`, `EvidenceSnapshot` | הסתרה אינה שקולה אוטומטית להגנה בליסטית; collision וה־LOD שומרים על מעבר מאושר. | `capabilities/geospatial_temporal/trees/` |
| `world.road` (primitive) | מקטע דרך עם חיבוריות, רוחב, משטח ומצב שימוש. | `terrain_world` · IMPLEMENT · M2 | `TerrainSample`, `SurfaceMaterial`, `CoordinateTime` | מסלול יכול להבחין בין דרך קיימת לדרך חסומה; זמן תחולה וגאומטריה נעולים. | `capabilities/geospatial_temporal/roads/` |
| `world.trench` (assembly) | תעלה עם חתך, כניסות, כיסוי ומגבלות תנועה. | `terrain_world` · IMPLEMENT · M2 | `TerrainSample`, `SurfaceMaterial`, `EvidenceSnapshot` | לוחם יכול להיכנס ולצאת רק בחיבור מאושר; גובה המצלמה אינו משנה כיסוי מכני. | `capabilities/geospatial_temporal/trenches/` |
| `world.locality` (assembly) | הרכבת שטח מוגבל, מבנים ותשתיות סביב לוקאליות היסטורית אחת. | `terrain_world` · IMPLEMENT · M2 | `TerrainSample`, `BuildingDefinition`, `RoadSegment`, `WaterBody`, `EvidenceSnapshot` | חבילה נטענת ללא קוד אפיזודה; כל רכיב שומר זהות, קואורדינטות ומקור/שחזור. | `capabilities/geospatial_temporal/localities/` |
| `world.coordinate_transform` (service) | המרת קואורדינטות עולם מדויקות למסגרת מקומית במטרים. | `terrain_world` · IMPLEMENT · M1 | `CoordinateTime`, `StableIdentity` | המרה הלוך וחזור ו־origin shift שומרים זהות ומרחק יחסי בתחום שגיאה מוצהר. | `game/runtime/geospatial_temporal/coordinates/` |
| `world.temporal_applicability` (service) | ייצוג תאריכים, טווחים, דיוק זמן ותחולה גאוגרפית בלי דיוק מדומה. | `temporal_world` · DEEP · M2 | `CoordinateTime`, `EvidenceClaim` | יום אינו מומר לשעה מומצאת; חפיפה לא ידועה או סותרת נשארת מפורשת. | `capabilities/geospatial_temporal/temporal_applicability/` |
| `world.historical_anchor` (primitive) | אילוץ היסטורי מתוארך ותחום עם מדיניות קונפליקט לבחירה מקומית. | `temporal_world` · DEEP · M2 | `ReviewedClaim`, `TemporalApplicability`, `EpisodeEnvelope` | גבול היסטורי אינו כופה מוות מוסתר או מאפס מלאי; קונפליקט מפיק החלטה רשומה. | `capabilities/geospatial_temporal/historical_anchors/` |
| `world.surface_state` (capability) | מצב רטיבות, בוץ, שלג/קרח ועקבות על חומר קרקע; הצטברות ושינוי עם הזמן. | `terrain_world` · IMPLEMENT · M3 | `SurfaceMaterial`, `WeatherModifier`, `TickClock` | גשם מוביל לאותו מצב קרקע שממנו ניידות ו־material קוראים; שמירה משחזרת אותו. | `capabilities/geospatial_temporal/world/surface_state/` |
| `world.fortification` (assembly) | הרכבת מחפורת, עמדת מגן, שקי חול ומחסה מחלקי מבנה וחומר. | `terrain_world` · IMPLEMENT · M2 | `BuildingEnvelope`, `SurfaceMaterial`, `TerrainSample` | collision, מעבר וקו ראייה תואמים גאומטריה; שייכות היסטורית דורשת מקור. | `capabilities/geospatial_temporal/world/fortification/` |
| `world.obstacle` (primitive) | מכשול מעבר כגון גדר, מחסום או הריסות עם מעטפת פיזית ויכולת הסרה. | `terrain_world` · IMPLEMENT · M3 | `TerrainSample`, `InteractionAffordance`, `AcceptedEvent` | ניווט ותנועה מסכימים על חסימה; שינוי מצב מייצר אירוע ועדכון מסלול. | `capabilities/geospatial_temporal/world/obstacle/` |
| `world.structure_state` (capability) | דלתות ופתחים, נזק למבנה והריסות ברמת פירוט מוגדרת. | `terrain_world` · IMPLEMENT · M3 | `DamageEffect`, `BuildingEnvelope`, `NavigationUpdate` | נזק משנה גם מעבר וגם תצוגה; אין צורך בסימולציית התמוטטות מלאה בגרסה הראשונה. | `capabilities/geospatial_temporal/world/structure_state/` |
| `world.day_night` (capability) | שעה, מיקום ומצב שמש/לילה כקלט לתאורה ולשגרה. | `temporal_world` · DEEP · M3 | `CoordinateTransform`, `TickClock`, `TemporalApplicability` | מזג אוויר ותאורה קוראים אותו שעון; האצת זמן אינה משנה תאריך מקור. | `capabilities/geospatial_temporal/world/day_night/` |

### קרבות, פעילויות וחוויית שחקן — 19 טיפוסים

קונטקסט: `context/game/domains/experience_design/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `experience.interaction` (capability) | פעולה תחומה בעלת תנאי זכאות, אפשרויות, זמן, מחיר ותוצאה נתפסת. | `experience_loop` · DESIGN · M3 | `InteractionProposal`, `ActorAction`, `SupplyTransfer`, `RelationshipEvent` | עזרה, בדיקת ציוד או שיתוף אספקה משנים מצב ממשי; ההדגמה כוללת לפחות שתי פעילויות שקטות. | `capabilities/experience_design/interactions/` |
| `experience.pacing` (capability) | בחירת הזדמנויות משחק ושקט לפי המצב הנוכחי ומטרת החוויה. | `experience_loop` · DESIGN · M3 | `EligibleInteraction`, `AuthorizedPlayerView`, `EpisodeEnvelope` | הבמאי אינו מייצר אויב, תחמושת או החייאה; אם אין פעולה מתאימה נשמר שקט. | `game/runtime/experience_design/pacing/` |
| `experience.profiles` (service) | מדיניות עזרה, נגישות וקושי שנפרדת מנאמנות היסטורית ופירוט מודל. | `experience_loop` · DESIGN · M3 | `GameplayModifier`, `AccessibilityPreference`, `EpisodeEnvelope` | אותן זהויות ואותן ראיות בכל פרופיל; שינוי קושי נרשם ואינו מוחק נפגעים מהיומן. | `capabilities/experience_design/profiles/` |
| `player.desktop_input` (capability) | מיפוי מקלדת, עכבר ובקר לפעולות משמעותיות הניתנות לשינוי. | `experience_interface` · IMPLEMENT · M1 | `SemanticAction`, `ActionValidation`, `AuthorizedPlayerView` | אותה פעולה עוברת validator זהה מ־desktop ומ־replay; remapping ומצבי hold/toggle פועלים. | `game/runtime/experience_design/desktop_input/` |
| `player.vr_boundary` (capability) | חוזה נפרד לראש/ידיים/גוף ולפעולות עם מתאם OpenXR ל־spike; בדיקת מכשיר ויציאת VR הן gates נפרדים. | `experience_interface` · IMPLEMENT · M1 | `SemanticAction`, `PoseSample`, `ActionValidation`, `AvatarState` | אובדן tracking מבטל input לא תקף; simulated XR מוכיח seam בלבד; אין דיווח על תאימות, נוחות או ביצועים בלי בדיקת headset. | `game/runtime/experience_design/vr_adapter/` |
| `player.comfort` (service) | מדיניות מצלמה, תנועה, recenter, pause ונוחות בישיבה או בעמידה. | `experience_interface` · IMPLEMENT · M1 | `ViewPose`, `LocomotionIntent`, `SessionLifecycle`, `AccessibilityPreference` | אין תנועת מצלמה כפויה ב־VR; pause ויציאה נגישים ואינם משנים עובדות היסטוריות. | `game/runtime/experience_design/comfort/` |
| `player.interface` (capability) | הוראות, כתוביות, משוב ויומן במבט מורשה עם מסלול מסכי ומרחבי. | `experience_interface` · IMPLEMENT · M3 | `AuthorizedPlayerView`, `SemanticAction`, `SubtitleCue` | עברית ו־RTL, ניגודיות וגודל קריאים; מידע נסתר אינו דולף דרך UI או כתוביות. | `game/runtime/experience_design/interface/` |
| `player.evidence_inspector` (capability) | הצגת מקור, שחזור וזהות סינתטית לפי בקשת השחקן ובתחום המותר. | `experience_interface` · IMPLEMENT · M3 | `InspectableEvidence`, `AuthorizedPlayerView`, `ContentLicense` | אפשר לשחק בלי לפתוח אטלס; בדיקה אינה חושפת פקודות עתידיות או זיכרון פרטי. | `game/runtime/experience_design/evidence_inspector/` |
| `battle.template` (assembly) | תבנית קרב נתונית הניתנת לשימוש חוזר: סיור, הגנה, התקפה או ליווי נבחרים בהרכבה מפורשת. | `experience_loop` · DESIGN · M3 | `BattleObjective`, `ForceRole`, `DeploymentRule`, `BattlePhase`, `HistoricalAnchor` | תבנית שנייה נטענת באותו loader וללא script אפיזודה; בחירת תבנית אינה טענה שאירוע כזה התרחש. | `capabilities/experience_design/battle_data/template/` |
| `battle.objective` (primitive) | יעד קרב מוגדר עם גורם אחראי, תנאי הצלחה/כישלון וחלופות מקומיות. | `experience_loop` · DESIGN · M3 | `ActorAuthority`, `WorldCondition`, `OutcomePolicy` | הצלחה נבחנת ממצב מאושר; הפסד אינו מאפס מלאי, פציעות או זמן באופן נסתר. | `capabilities/experience_design/battle_data/objective/` |
| `battle.condition` (primitive) | תנאי ו־trigger הצהרתי מוגבל על זמן, מקום, פקודה או מצב מאושר. | `experience_loop` · DESIGN · M3 | `AuthorizedPredicate`, `TickClock`, `AcceptedEvent` | חבילה אינה מריצה קוד; predicate לא מוכר נדחה והתנאי אינו קורא ידע אסור. | `capabilities/experience_design/battle_data/condition/` |
| `battle.force_role` (primitive) | תפקיד כוח כמו מגן, סייר, עתודה או מלווה עם שיוך יחידה ותחום סמכות. | `experience_loop` · DESIGN · M3 | `DatedOrganization`, `RoleAssignment`, `EvidenceSnapshot` | צד ותפקיד אינם ממציאים נוכחות יחידה; התנהגות משתמשת באותן יכולות command ו־AI. | `capabilities/experience_design/battle_data/force_role/` |
| `battle.deployment` (primitive) | נתוני מיקום התחלתי והגעה של כוחות בעלי חלון זמן, מקור ומדיניות reinforcement. | `experience_loop` · DESIGN · M3 | `CoordinateTransform`, `TemporalApplicability`, `ActorTransfer`, `HistoricalAnchor` | אין teleport תוך כדי משחק או יצירת אדם כפול; הגעה חסרת ראיה מסומנת כשחזור/סימולציה. | `capabilities/experience_design/battle_data/deployment/` |
| `battle.phase` (primitive) | שלב טקטי עם תנאי כניסה/יציאה, משימות מותרות וקשר לשלבים הבאים. | `experience_loop` · DESIGN · M3 | `WorldCondition`, `BattleObjective`, `OrderDelivery` | התקדמות שלב אינה מכריחה תוצאה היסטורית או מחליפה מצב עולם; שקט מותר אם התנאים לא התקיימו. | `capabilities/experience_design/battle_data/phase/` |
| `battle.anchor_policy` (primitive) | מדיניות תחומה לפתרון התנגשות בין אילוץ היסטורי לתוצאות מקומיות. | `experience_loop` · DESIGN · M3 | `HistoricalAnchor`, `EpisodeEnvelope`, `LocalConsequence` | קונפליקט מייצר החלטה מפורשת; אין הרג כפוי, החייאה או תיקון עבר שקט. | `capabilities/experience_design/battle_data/anchor_policy/` |
| `battle.outcome` (primitive) | תוצאה מקומית של קרב עם שינויים במצב, מקורות ותנאי סיום. | `experience_loop` · DESIGN · M3 | `AcceptedEvent`, `ResourceAccount`, `CasualtyState`, `RelationshipEvent` | תוצאה שומרת נפגעים ומלאי; תוצאת משחק אינה נכתבת בחזרה ל־HistoricalTruth. | `capabilities/experience_design/battle_data/outcome/` |
| `battle.difficulty_overlay` (primitive) | שכבת עזרה וחוויית שחקן מעל תבנית קרב, ללא שינוי הגדרות היסטוריות. | `experience_loop` · DESIGN · M3 | `GameplayModifier`, `AccessibilityPreference`, `BattleTemplate` | Easy ו־High Fidelity חולקים ציוד וזהויות; שינויים בפגיעה/רמזים נרשמים באופן גלוי. | `capabilities/experience_design/battle_data/difficulty_overlay/` |
| `player.body` (capability) | ייצוג וקלט של גוף, ראש וידיים; מפיק כוונת יציבה/תנועה/ישיבה בלבד. infantry_actions מחזיק תנועה ויציבה מוסמכות; ground_platform מחזיק תפוסת עמדה. | `experience_interface` · IMPLEMENT · M1 | `AvatarState`, `PoseSample`, `CrewStation`, `ActionValidation` | הראש אינו חייב לשנות כיוון גוף; semantic actions מאומתות אצל בעל המצב; כניסה לרכב אינה משכפלת אדם או משנה תפוסה מצד renderer. | `capabilities/experience_design/player/body/` |
| `experience.activity` (assembly) | מתכון פעילות: אכילה, תחזוקה, שמירה, אימון, מכתב או עזרה, עם משך וחברה. | `experience_loop` · DESIGN · M3 | `InteractionProposal`, `FatigueState`, `RelationshipEvent`, `SupplyTransfer` | פעילות שקטה משנה צורך/יחס/משאב או ידע מורשה; אפשר להבין מה לעשות בלי הרצאה. | `capabilities/experience_design/experience/activity/` |

### חיילים וציוד אישי — 8 טיפוסים

קונטקסט: `context/game/domains/infantry/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `actor.human` (primitive) | גוף אדם סימולטיבי בעל זהות יציבה, ממדים, מצב פעולה ויכולות בסיס. | `infantry_actions` · IMPLEMENT · M2 | `CharacterIdentity`, `BodyEnvelope`, `InjuryState` | זהות הגוף נשמרת בין rigs ו־LOD; אדם מת אינו ממשיך לבצע פעולות חיים. | `capabilities/infantry/primitives/human/` |
| `infantry.carried_equipment` (assembly) | לבוש, ציוד אישי ונשק נישא התואמים יחידה, תפקיד, מקום וזמן. | `infantry_actions` · IMPLEMENT · M2 | `VariantEvidence`, `InventoryView`, `AttachmentBinding` | הפריט המוצג הוא הפריט במלאי; משקל והשמטה עוברים דרך ledger. | `capabilities/infantry/assemblies/carried_equipment/` |
| `infantry.locomotion` (capability) | הליכה, פנייה, כריעה ומעבר בסיסי מול מעטפת גוף ומשטח. | `infantry_actions` · IMPLEMENT · M3 | `TerrainSample`, `Traversability`, `BodyEnvelope`, `AcceptedPhysicsOutcome` | עמידה וכריעה משנות collision וכיסוי בעקביות; input אינו עוקף מגבלת תנועה. | `game/runtime/infantry/locomotion/` |
| `infantry.squad_formation` (capability) | תנועה, המתנה והתקבצות של חוליה עם מרחקים ותפקידים. | `infantry_actions` · IMPLEMENT · M3 | `OrderDelivery`, `NavigationPath`, `ActorAction`, `RoleAssignment` | חבר מופרד נשאר מופרד עד מסלול ממשי; אין teleport או ידיעה גלובלית. | `game/runtime/infantry/squad_formation/` |
| `infantry.injury` (capability) | פציעה, אובדן יכולת ומוות כמצבים מתמידים בעלי סיבה וזמן. | `infantry_casualty` · IMPLEMENT · M3 | `DamageEffect`, `HumanBody`, `AcceptedEvent` | פציעה ומוות נשמרים ב־save וב־LOD; דיכוי ומורל אינם מחליפים את מצב הפציעה. | `game/runtime/infantry/injury/` |
| `infantry.care` (capability) | פעולת סיוע מוגבלת שמחייבת אדם מתאים, זמן ומשאבים. | `infantry_casualty` · IMPLEMENT · M3 | `InjuryState`, `InventoryTransfer`, `ActorAction`, `InteractionEligibility` | סיוע נקטע ומחודש לפי חוזה; זמן וציוד נגבים ואין ריפוי ללא פעולה מאושרת. | `game/runtime/infantry/care/` |
| `infantry.condition` (capability) | עייפות, מאמץ, שינה, רעב/צמא וחשיפה כמודל משחק מוצהר; נפרד מפציעה. | `infantry_casualty` · IMPLEMENT · M3 | `WeatherModifier`, `SupplyTransfer`, `ActivityEvent`, `TickClock` | FatigueState מופק כאן בלבד; שינה/ארוחה/מזג אוויר משפיעים; save ו־LOD משמרים מצב. | `capabilities/infantry/infantry/condition/` |
| `infantry.wearable` (assembly) | מדים, קסדה, נעליים, תיק וציוד אישי עם תוקף דגם, slots ומשקל. | `infantry_actions` · IMPLEMENT · M2 | `VariantEvidence`, `AttachmentBinding`, `ResourceAccount` | פריט נראה תואם למלאי ולזהות ההיסטורית; החלפת LOD אינה משנה ציוד. | `capabilities/infantry/infantry/wearable/` |

### אנשים, זיכרון ויחסים — 7 טיפוסים

קונטקסט: `context/game/domains/characters/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `character.identity` (primitive) | CharacterId רציף עם שם, רקע, מעמד אמיתי או סינתטי ומקורות מפורשים. | `character_identity` · DESIGN · M2 | `StableIdentity`, `ReviewedClaim`, `RoleAssignment` | החלפת לבוש, render ו־LOD אינה מחליפה אדם; ביוגרפיה מומצאת אינה מיוחסת כאמת לאדם אמיתי. | `capabilities/characters/identity/` |
| `character.commitments` (capability) | מחויבויות, תפקידים והבטחות מתמשכות של אדם לאורך זמן. | `character_identity` · DESIGN · M3 | `OrderDelivery`, `AcceptedInteraction`, `CharacterIdentity` | הבטחה נשמרת אחרי טעינה; משימה מנוגדת דורשת עדכון או קונפליקט גלוי. | `game/runtime/characters/commitments/` |
| `character.memory` (capability) | זיכרון מתמיד של אירוע נתפס, עדים, זמן ומקור הידיעה. | `character_memory` · IMPLEMENT · M3 | `ActorObservation`, `AcceptedInteraction`, `AcceptedEvent` | אדם זוכר רק אירוע שהיה עד לו או שנמסר לו; הזיכרון אינו חי רק בחלון LLM. | `game/runtime/characters/memory/` |
| `character.knowledge` (service) | מאגר אמונות וידיעות של אדם עם מקור, זמן מסירה ואפשרות לטעות. | `character_memory` · IMPLEMENT · M3 | `ObservationDelivery`, `OrderDelivery`, `MemoryRecord` | שמועה נשארת אמונה בעלת מקור; אין קריאה ישירה לעולם האמת או לעתיד. | `game/runtime/characters/knowledge/` |
| `character.relationship` (capability) | קשר מכוון בין אנשים המשתנה בעקבות פעולות שנחוו. | `character_social` · DESIGN · M3 | `CharacterIdentity`, `AcceptedInteraction`, `MemoryRecord` | עזרה שעלותה זמן או ציוד יכולה לשנות קשר; השינוי נשמר ומכבד כיוון ופרטיות. | `game/runtime/characters/relationships/` |
| `character.dialogue` (capability) | דיבור ותגובות דרך הצעה תחומה, תנאי זכאות ובדיקת ידע. בסיס M3 הוא תוכן מוגבל ומתוסרט; הרחבת שיחת LLM מתמשכת עתידית ואינה תנאי לפרוסה. | `character_social` · DESIGN · M3 | `ActorKnowledge`, `InteractionProposal`, `RelationshipView` | דיאלוג מקומי פועל ללא מודל רשת; טקסט אינו יוצר תחמושת, ידיעה או פעולה שלא אושרו. | `game/runtime/characters/dialogue/` |
| `character.routines` (capability) | לוח פעילויות של שינה, אוכל, שמירה, עבודה ופנאי עם הפרעות. | `character_social` · DESIGN · M5 | `ActivityIntent`, `ResourceAccount`, `OrderDelivery`, `FatigueState` | אזעקה ופקודה קוטעות פעילות לפי מדיניות; זמן, עייפות וקשר נשמרים גם מחוץ למסך. | `game/runtime/characters/routines/` |

### יחידות, פקודות וקשר — 5 טיפוסים

קונטקסט: `context/game/domains/command_organization/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `command.organization` (assembly) | מבנה יחידות, תפקידים ושיוכים בעלי תחולה בזמן. | `command_structure` · RESEARCH · M2 | `ReviewedClaim`, `TemporalApplicability`, `CharacterIdentity` | שייכות ל־OOB אינה מוכיחה נוכחות טקטית; שינוי שיוך מתוארך ובעל מקור. | `capabilities/command_organization/organization/` |
| `command.authority` (service) | בדיקת סמכות לפי תפקיד, יחידה, זמן ומצב תקשורת. | `command_structure` · RESEARCH · M3 | `DatedOrganization`, `RoleAssignment`, `ActorKnowledge` | פקודה שלא הונפקה בסמכות נדחית; תפקיד חסר אינו ניחוש אוטומטי. | `game/runtime/command_organization/authority/` |
| `command.orders` (capability) | יצירה, מסירה, אישור, עדכון וביטול של פקודה גרסתית. | `command_structure` · RESEARCH · M3 | `CommandAuthority`, `OrderDelivery`, `ActorKnowledge`, `AcceptedEvent` | מקבל פועל רק אחרי מסירה; ביטול ואישור אינם נעלמים ב־save או בהחלפת LOD. | `game/runtime/command_organization/orders/` |
| `equipment.radio` (primitive) | מכשיר קשר עם תאימות, ערוץ, טווח שימוש, הספק ומצב תפעולי. | `command_signals` · IMPLEMENT · M2 | `VariantEvidence`, `ResourceAccount`, `CommunicationEnvelope` | קשר תואם וריאנט ומצב מלאי; אין קליטה אוטומטית בגלל שייכות לאותה יחידה. | `capabilities/command_organization/primitives/radio/` |
| `command.communications` (capability) | מסירת קשר רדיו, קול או שליח עם עיכוב, תקלות ואישור. | `command_signals` · IMPLEMENT · M3 | `CommunicationEnvelope`, `TerrainSample`, `WeatherSample`, `ActorTransfer`, `AcceptedEvent` | מסר שלא הגיע אינו ידע; ידיעת השולח אינה מעניקה למקבל זיכרונות פרטיים. | `game/runtime/command_organization/communications/` |

### אספקה ותחזוקה — 6 טיפוסים

קונטקסט: `context/game/domains/logistics/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `logistics.stock` (primitive) | חשבון מלאי בעל סוג, כמות, יחידה, בעלים ומיקום. | `logistics_supply` · IMPLEMENT · M2 | `StableIdentity`, `Units`, `AcceptedEvent` | יתרה לעולם אינה נוצרת מקרבה למחסן; כל שינוי מקושר לאירוע והיחידות תואמות. | `capabilities/logistics/stock/` |
| `logistics.transfer` (capability) | העברת אספקה אטומית בין מלאים עם קיבולת, אובדן וזמן. | `logistics_supply` · IMPLEMENT · M3 | `ResourceAccount`, `LoadEnvelope`, `AcceptedEvent` | העברה חוזרת אינה מכפילה חומר; מקור ויעד מתאזנים או אובדן מתועד. | `game/runtime/logistics/transfers/` |
| `logistics.supply_route` (capability) | הקצאת תובלה ודרך למענה על ביקוש בעל deadline. | `logistics_supply` · IMPLEMENT · M3 | `DemandRequest`, `TransportCapacity`, `RouteAvailability`, `OrderDelivery` | דרך זמינה אינה אספקה שהגיעה; הגעה, צריכה ואיחור נובעים מאירועים ממשיים. | `game/runtime/logistics/supply_routes/` |
| `logistics.maintenance` (capability) | בדיקה ותחזוקה מתוכננת לפי ציוד, זמן, כשירות וחלקים. | `logistics_maintenance` · IMPLEMENT · M3 | `ComponentCondition`, `WorkOrder`, `ResourceAccount`, `ActorAction` | פעולת תחזוקה משנה מצב רק אחרי משך ומשאבים מתאימים; אפשר להפסיקה. | `game/runtime/logistics/maintenance/` |
| `logistics.repair` (capability) | תיקון כשל רכיב באמצעות יכולת איש צוות, גישה וחלקי חילוף. | `logistics_maintenance` · IMPLEMENT · M3 | `ComponentCondition`, `RepairEnvelope`, `SupplyTransfer`, `ActorAction` | תיקון לא נתמך מחזיר חוסר; אין החזרת כלי שלם לתפקוד באמצעות תיקון קוסמטי. | `game/runtime/logistics/repair/` |
| `logistics.resource_definition` (primitive) | זהות וכמות של מזון, מים, דלק, תחמושת וחלפים עם יחידות ותאימות. | `logistics_supply` · IMPLEMENT · M2 | `SIQuantity`, `VariantEvidence` | אי אפשר לחבר יחידות/פריטים שונים באותו חשבון; חוסר אספקה אינו אפס לא מסומן. | `capabilities/logistics/logistics/resource_definition/` |

### מראה, הנפשה, קול וכלי תצוגה — 12 טיפוסים

קונטקסט: `context/game/domains/asset_pipeline/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `asset.mesh` (service) | בניית מודל גוף, מבנה או ציוד התואם וריאנט עם scale, collision ו־LOD. | `assets_visual` · VISUAL · M3 | `VariantDefinition`, `HistoricalIdentityFeatures`, `GeometryEnvelope` | silhouette, קנה מידה ונקודות חיבור תואמים הגדרה מאושרת; placeholder מסומן ואינו עובר promotion. | `capabilities/asset_pipeline/meshes/` |
| `asset.material` (service) | חומרים וטקסטורות תואמי דגם עם profile desktop ותקציבי VR עתידיים. | `assets_visual` · VISUAL · M3 | `SurfaceMaterial`, `WeatherSample`, `AssetProfile`, `SurfaceState` | ב־desktop נשמרות זהות ויחידות; בדיקת stereo ושתי עיניים היא gate נפרד על מכשיר לפני טענת תמיכה ב־VR. | `capabilities/asset_pipeline/materials/` |
| `asset.import_manifest` (service) | נעילת תוכן, רישיון, מקור, פורמט והגדרות ייבוא ל־Godot. | `assets_visual` · IMPLEMENT · M1 | `ContentHash`, `ContentLicense`, `VariantBinding`, `AssetProfile` | URL לבדו אינו lock; קובץ glTF ומקור נשמרים, יחידות ו־hash נבדקים לפני טעינה. | `capabilities/asset_pipeline/import_manifests/` |
| `asset.rig` (service) | שלד, anchors לידיים ואחיזה וקישור גוף למלבוש או ציוד. | `assets_motion` · IMPLEMENT · M3 | `BodyEnvelope`, `AttachmentBinding`, `GripAnchor` | האחיזה במטרים; pose מוסק מסומן ככזה וראש NPC אינו משתלט על מבט משתמש VR. | `capabilities/asset_pipeline/rigs/` |
| `asset.animation` (capability) | לוקומוציה, מחוות, מבט ופעולות המחשה הנגזרות ממצב פעולה מאושר. | `assets_motion` · IMPLEMENT · M3 | `AnimationActionView`, `AvatarState`, `AcceptedEvent` | אנימציה אינה משלימה reload או סיוע בעצמה; גוף מת/פצוע מציג את מצבו בפועל. | `game/runtime/asset_pipeline/animation/` |
| `asset.spatial_audio` (capability) | קול סביבתי, נשק, צעדים ומקורות קול במיקום עולם עם תקציבי ביצוע. | `assets_audio` · IMPLEMENT · M3 | `AcousticEvent`, `AuthorizedListenerView`, `WeatherSample` | כיוון ומרחק עקביים עם עולם; איכות HRTF דורשת בדיקה ואינה מוסקת מעצם קיום panning. | `game/runtime/asset_pipeline/spatial_audio/` |
| `asset.voice_subtitles` (service) | תוכן קולי וכתוביות שפה עם תזמון, זכויות וזיקה להצעת דיבור מאושרת. | `assets_audio` · DESIGN · M3 | `ValidatedSpeechProposal`, `ContentLicense`, `SubtitleCue` | הקול אינו מוסיף עובדות או דובר חסר; כתוביות מסונכרנות וקריאות כולל RTL. | `capabilities/asset_pipeline/voice_subtitles/` |
| `asset.visual_binding` (primitive) | קישור מפורש בין VariantId, חלקים, sockets, mesh, חומר ו־LOD. | `assets_visual` · IMPLEMENT · M1 | `VariantDefinition`, `AttachmentBinding`, `ContentHash` | אי התאמה בין turret/hull/weapon/asset נדחית; אין החלפה אסתטית סמויה של תת־דגם. | `capabilities/asset_pipeline/asset/visual_binding/` |
| `asset.vfx` (capability) | אפקטים חזותיים לאירוע ירי/פגיעה, עשן, אבק, אש ומשקעים. | `assets_visual` · VISUAL · M3 | `AcceptedEvent`, `WeatherSample`, `ObscurantState`, `AssetProfile` | נגזר רק מאירוע/מצב מוסמך; אפקט אינו פוגע, מייצר תחמושת או משנה תפיסה בעצמו. | `capabilities/asset_pipeline/asset/vfx/` |
| `asset.environment_light` (capability) | שמיים, שמש, תאורת פנים/חוץ, פנסים וחשיפה אסתטית לפי מצב עולם. | `assets_visual` · VISUAL · M3 | `DayNightSample`, `WeatherSample`, `AssetProfile` | החלפת renderer/profile שומרת אירועי זמן וראות; ביצועים נמדדים; VR stereo נבדק בשער מכשיר. | `capabilities/asset_pipeline/asset/environment_light/` |
| `asset.decals` (service) | סימני בוץ, עקבות, שחיקה ופגיעות, מוגבלים בתקציב ומשך חיים. | `assets_visual` · VISUAL · M3 | `SurfaceState`, `AcceptedEvent`, `AssetProfile` | סימן קוסמטי אינו ראיה היסטורית או מקור נזק; LOD מפחית אותו בלי לאבד מצב מוסמך. | `capabilities/asset_pipeline/asset/decals/` |
| `asset.catalog_preview` (service) | כלי פיתוח לקטלוג, בדיקת רכיבים, variant inspector ותצוגת sandbox. | `assets_visual` · IMPLEMENT · M3 | `VariantDefinition`, `ContentHash`, `AssetProfile` | מסך טוען manifest אמיתי ומסמן חסרים; אינו מוצג כחלק חובה של חוויית השחקן. | `capabilities/asset_pipeline/asset/catalog_preview/` |

### תפיסה, החלטה וניווט — 6 טיפוסים

קונטקסט: `context/game/domains/ai_navigation/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `perception.vision` (capability) | תצפית חזותית תחומה לפי כיוון, חסימות, אור, מזג אוויר וחיישן. | `ai_perception` · IMPLEMENT · M3 | `SensorEnvelope`, `CollisionQuery`, `WeatherSample`, `ActorPose`, `ObscurantState`, `DayNightSample`, `VisibilityEnvelope` | חסימה מונעת תצפית; יש הבדל בין זיהוי עצם, זיהוי צד וזיהוי זהות. | `game/runtime/ai_navigation/vision/` |
| `perception.hearing` (capability) | אירוע שמיעה מקומי עם כיוון, עוצמה ואי־ודאות, בלי גישה למקור נסתר בשלמותו. | `ai_perception` · IMPLEMENT · M3 | `AcousticEvent`, `SurfaceMaterial`, `WeatherSample`, `ActorPose` | שמיעת ירייה אינה מעניקה שם ותפקיד היורה; גבולות זמן וטווח נאכפים. | `game/runtime/ai_navigation/hearing/` |
| `perception.observation` (service) | איחוד חיישנים לתצפית חתומה בזמן ובמקור שנמסרת לשחקן או ל־NPC. | `ai_perception` · IMPLEMENT · M3 | `VisionObservation`, `HearingObservation`, `ActorKnowledge` | תצפית מסופקת דרך projection; ביטחון חיישן אינו שווה לוודאות היסטורית. | `game/runtime/ai_navigation/observation/` |
| `ai.navigation` (capability) | נתיב מקומי ותיקון נתיב לפי עבירות, מעטפת גוף וידיעה מותרת. | `ai_decision` · IMPLEMENT · M3 | `Traversability`, `NavigationRequest`, `MobilityEnvelope`, `ActorObservation` | אין מסלול דרך מעבר בלתי עביר; מידע על סכנה נסתרת אינו מוזרק דרך העלות. | `game/runtime/ai_navigation/navigation/` |
| `ai.cognition` (capability) | בחירת כוונה בעץ מצבים או utility planner מתוך ידע, תפקיד ומשימה. | `ai_decision` · IMPLEMENT · M3 | `ActorKnowledge`, `OrderDelivery`, `ActivityIntent`, `InteractionEligibility` | follow, wait, cover, task ו־aid עובדים ללא LLM ברשת; כוונה נבדקת לפני שינוי מצב. | `game/runtime/ai_navigation/cognition/` |
| `ai.morale` (capability) | נכונות והתמדה בפעולה המושפעות מפחד, עייפות, קשר וחשיפה נתפסת. | `ai_decision` · IMPLEMENT · M3 | `SuppressionEvent`, `FatigueState`, `RelationshipView`, `ActorKnowledge` | מורל ודיכוי זמני נפרדים מפציעה; התנהגות ניתנת לשחזור ואין הסקת אמת ממנה. | `game/runtime/ai_navigation/morale/` |

### תעופה — הרחבה לפי צורך — 4 טיפוסים

קונטקסט: `context/game/domains/aviation/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `equipment.aircraft` (assembly) | תצורת מטוס הכוללת גוף, כנפיים, עמדות, מטען ונתוני וריאנט. | `aviation_platform` · IMPLEMENT · FUTURE | `VariantEvidence`, `MassProperties`, `WeaponMount`, `AssetBinding` | זהות המטוס וגרסתו תואמות מקורות ונכסים; הופעה היסטורית דורשת ראיית נוכחות נפרדת. | `capabilities/aviation/assemblies/aircraft/` |
| `aviation.propulsion_adapter` (capability) | התאמת מנוע צירי או הנעה ייעודית לדחף אווירי ולתנאי הטיסה. | `aviation_platform` · IMPLEMENT · FUTURE | `ShaftPower`, `FuelCompatibility`, `AirState`, `VariantEvidence` | ליבת המנוע המשותפת אינה קובעת עקומת דחף; המתאם מכייל ומצהיר על מעטפתו. | `game/runtime/aviation/propulsion/` |
| `aviation.flight` (capability) | מצב טיסה ותנועה במעטפת אווירודינמית שנבחרה במפורש. | `aviation_platform` · IMPLEMENT · FUTURE | `AirframeDefinition`, `PropulsionOutput`, `WeatherSample`, `AcceptedPhysicsOutcome` | מהירות, גובה ומטען נבדקים בתחום המודל; אין שימוש בנתוני טנק או כלי שיט. | `game/runtime/aviation/flight/` |
| `aviation.sortie` (capability) | תכנון וביצוע גיחה עם זמן, טווח, מטען ודיווח תצפית שנמסר. | `aviation_platform` · IMPLEMENT · FUTURE | `FlightEnvelope`, `SupplyTransfer`, `OrderDelivery`, `ObservationDelivery` | הגעה וצריכה נשמרות; תצפית אינה זמינה לפני מסירה ולא מוכיחה היסטוריה. | `game/runtime/aviation/sortie/` |

### ים — הרחבה לפי צורך — 4 טיפוסים

קונטקסט: `context/game/domains/naval/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `equipment.ship` (assembly) | כלי שיט עם גוף צף, מדורים, סיפון, מטען ומערכות ייעודיות. | `naval_platform` · IMPLEMENT · FUTURE | `VariantEvidence`, `MassProperties`, `WeaponMount`, `AssetBinding` | גבולות עומס ומידות תואמים וריאנט; מדורי אונייה אינם מיובאים ממודל רכב קרקעי. | `capabilities/naval/assemblies/ship/` |
| `naval.propulsion_adapter` (capability) | המרת הספק למערכת הנעה ימית ותצרוכת לפי תצורת כלי השיט. | `naval_platform` · IMPLEMENT · FUTURE | `ShaftPower`, `FuelCompatibility`, `WaterSample`, `VariantEvidence` | עקומת דחף/גרר ימית בעלת מקור או הנחה; חוזה משותף אינו מעניק גישה למסמכי קרקע. | `game/runtime/naval/propulsion/` |
| `naval.movement` (capability) | תנועה ימית ותמרון לפי עומק, חוף, זרם ומעטפת כלי שיט. | `naval_platform` · IMPLEMENT · FUTURE | `WaterSample`, `SeaRoute`, `PropulsionOutput`, `WeatherSample`, `AcceptedPhysicsOutcome` | נתיב בעל עומק חסר אינו מאושר בוודאות; מטען ומהירות משפיעים לפי מודל מוצהר. | `game/runtime/naval/movement/` |
| `naval.transport_operation` (capability) | הובלה, העלאה והורדה של אנשים ומטען במתקן מורשה. | `naval_platform` · IMPLEMENT · FUTURE | `VesselCapacity`, `PortAccess`, `SupplyTransfer`, `ActorTransfer`, `OrderDelivery` | אין שכפול מטען או אדם בשתי פלטפורמות; זמן ומגבלות העברה נרשמים. | `game/runtime/naval/transport_operations/` |

### מנוע, הרכבה והתמדה — 11 טיפוסים

קונטקסט: `context/game/domains/simulation_runtime/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `runtime.ecs` (service) | רישום רכיבים וזהויות עם בעלות כתיבה מפורשת ומבטים מורשים. | `runtime_core` · DEEP · M1 | `StableIdentity`, `ComponentSchema`, `StateTransition` | לכל שדה כותב מורשה; רכיב או schema לא מוכר נדחים במקום הוספה שקטה. | `game/runtime/simulation_runtime/ecs/` |
| `runtime.schedule` (service) | תזמון tick קבוע, סדר מערכות ושעונים מקומיים מוכרזים. | `runtime_core` · DEEP · M1 | `TickClock`, `SystemDeclaration`, `SeededRandom` | סדר ריצה קבוע ומוכח; אין מחקר, רשת או תשלום ב־tick. | `game/runtime/simulation_runtime/schedule/` |
| `runtime.physics_port` (service) | גבול physics/navigation המקבל פקודות ומחזיר תוצאות מאושרות מה־backend הנעול. | `runtime_core` · DEEP · M1 | `PhysicsRequest`, `NavigationRequest`, `AcceptedPhysicsOutcome` | live-headless מפעיל את אותו backend; recorded outcomes מסומנים כמסלול replay נפרד. | `game/runtime/simulation_runtime/physics_port/` |
| `runtime.events` (service) | סדר אירועים, סיבות, ייחודיות ו־RNG בתחום determinism מפורש. | `runtime_core` · DEEP · M1 | `AcceptedCommand`, `StateTransition`, `EventIdentity` | אירוע חוזר אינו מיושם פעמיים; hash משוחזר לפי lock וסדר קלט מוגדרים. | `game/runtime/simulation_runtime/events/` |
| `runtime.actor_projection` (service) | סינון מצב עולם למבט שחקן או NPC על בסיס מידע שנמסר בלבד. | `runtime_core` · DEEP · M3 | `ObservationDelivery`, `ActorKnowledge`, `VisibilityPolicy` | זהות של אויב נסתר אינה דולפת דרך UI, path או debug; פרטי אמת חסומים לפני מסירה. | `game/runtime/simulation_runtime/actor_projection/` |
| `runtime.episode_loader` (service) | טעינת EpisodeSpec, רכיבים ונכסים לפי גרסאות, hashes והתקנות מורשות. | `runtime_core` · DEEP · M1 | `EpisodeSpec`, `CapabilityLock`, `AssetManifest`, `ValidationReceipt` | אפיזודה שנייה נטענת מנתונים באותו build; חבילה אינה מתקינה קוד או משנה schedules. | `game/runtime/simulation_runtime/episode_loader/` |
| `runtime.lod` (capability) | מעבר בין רמות סימולציה ושמירת מצב של יחידים וקבוצות. | `runtime_continuity` · IMPLEMENT · M5 | `StateSnapshot`, `AggregateState`, `ResourceAccount`, `ActorContinuity` | מעבר הלוך וחזור שומר אנשים, פציעות, מלאי, פקודות וקשרים לפי קירוב מוצהר. | `game/runtime/simulation_runtime/lod/` |
| `runtime.save` (service) | צילום מצב וטעינה עם נעילת תוכן ו־schema ומיגרציה מפורשת. | `runtime_continuity` · IMPLEMENT · M1 | `StateSnapshot`, `EpisodeLock`, `ContentHash`, `MigrationPlan` | שמירה נטענת באותו lock; מקור או plugin חדשים אינם משנים משחק קיים בשקט. | `game/runtime/simulation_runtime/save/` |
| `runtime.replay` (service) | בדיקת שחזור החלטות לפי פקודות ותוצאות קודמות, ובנפרד הרצה פיזיקלית חוזרת. | `runtime_continuity` · IMPLEMENT · M1 | `AcceptedCommand`, `AcceptedPhysicsOutcome`, `EventLog`, `EpisodeLock` | שני סוגי ההוכחה מדווחים בנפרד; hash זהה במסלול מוקלט אינו הוכחת determinism של physics. | `game/runtime/simulation_runtime/replay/` |
| `runtime.time_acceleration` (capability) | קידום זמן מוסכם עם עצירה לפני אירוע מקומי משמעותי ועיבוד אילוצים. | `runtime_continuity` · IMPLEMENT · M5 | `TickClock`, `HistoricalAnchor`, `ActivitySchedule`, `PendingOrder` | אין דילוג על אירוע היסטורי או מחיקה של חוב אספקה; פעולה דורשת בקשת שחקן. | `game/runtime/simulation_runtime/time_acceleration/` |
| `runtime.battle_evaluator` (capability) | הערכת תנאים ושלבי תבנית נתונית בסדר אירועים מוגדר, בלי קוד אפיזודה שרירותי. | `runtime_core` · DEEP · M3 | `BattleTemplate`, `AuthorizedPredicate`, `AcceptedEvent`, `TickClock` | predicate לא מוכר או מחזור ללא גבול נדחים; replay משמר תוצאה; runtime אינו ממציא טענה היסטורית. | `capabilities/simulation_runtime/runtime/battle_evaluator/` |

### מקורות, טענות ואי־ודאות — 6 טיפוסים

קונטקסט: `context/game/domains/historical_evidence/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `evidence.source` (primitive) | רשומת מקור: ארכיון, מחבר, תאריך, גרסה ורישיון; ללא הסקת אמיתות מעצם קיום המקור. | `evidence_sources` · RESEARCH · M2 | `StableIdentity`, `ContentLicense` | אפשר לאתר את המהדורה שנקראה ואת מגבלות השימוש; מקור חסר מוחזר כחוסר מפורש. | `capabilities/historical_evidence/sources/` |
| `evidence.locator` (primitive) | מיקום מדויק של ראיה בעמוד, פסקה, מפה או קטע קול. | `evidence_sources` · RESEARCH · M2 | `SourceRecord`, `CoordinateTime` | הפניה חוזרת לאותה נקודה במקור והחילוץ שומר שפה, יחידות ואי־ודאות. | `capabilities/historical_evidence/locators/` |
| `evidence.snapshot` (assembly) | חבילת ראיות נעולה עבור מקום, זמן וזהויות מוגדרים. | `evidence_sources` · RESEARCH · M2 | `ReviewedClaim`, `ContentHash`, `ScopeGrant` | תוכן החבילה משוחזר לפי hash; עדכון מקור יוצר גרסה חדשה ולא משנה save פעיל. | `capabilities/historical_evidence/snapshots/` |
| `evidence.claim` (primitive) | טענה ברמת שדה עם מקור, תחולה, מידת ודאות ומצב ביקורת נפרדים. | `evidence_claims` · RESEARCH · M2 | `SourceLocator`, `StableIdentity`, `CoordinateTime` | טענה מועמדת אינה הופכת לאמת ללא החלטת סוקר בלתי תלוי; זמן ווריאנט שגויים נדחים. | `capabilities/historical_evidence/claims/` |
| `evidence.contradiction` (service) | רישום מחלוקות בין מקורות והצגת חלופות ללא הכרעה אוטומטית. | `evidence_claims` · RESEARCH · M2 | `EvidenceClaim`, `SourceLocator` | שתי הגרסאות והיקף הסתירה נשמרים; היעדר הכרעה אינו מקבל תווית VERIFIED. | `capabilities/historical_evidence/contradictions/` |
| `evidence.reconstruction` (service) | הצהרת הנחות, שיטה וטווח תוקף לפרטים שהמקורות אינם מכריעים. | `evidence_claims` · RESEARCH · M2 | `ReviewedClaim`, `ReconstructionPolicy` | כל ערך משוחזר מזוהה כשחזור; איכות חזותית או schema תקין אינם משנים את סמכותו. | `capabilities/historical_evidence/reconstruction/` |

### בנייה, ספקים ועלויות — 5 טיפוסים

קונטקסט: `context/game/domains/economy_deliver/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `build.capability_provider` (service) | אותו חוזה ביצוע מקומי או adapter ל־Deliver עבור משימת בנייה מחוץ ל־runtime. | `economy_provider` · IMPLEMENT · M1 | `CapabilityRequest`, `CapabilityResult`, `ScopeGrant` | builder מקומי מייצר תוצר בלי Deliver ובלי רשת; תקלה חיצונית אינה תלות של tick. | `capabilities/economy_deliver/provider/` |
| `build.quote_reservation` (service) | quote מאושר ורזרבה לפני פעולה בתשלום עם זהות בקשה יציבה. | `economy_provider` · IMPLEMENT · M3 | `CapabilityRequest`, `PriceQuote`, `BudgetAccount` | אין ביצוע בתשלום לפני quote; retry עם אותו input אינו קונה אותה עבודה שוב. | `capabilities/economy_deliver/quotes/` |
| `build.investment` (service) | בחירת השקעת fidelity לפי חוסר היסטורי, תרומה לחוויה, עלות ושימוש חוזר. | `economy_provider` · IMPLEMENT · M3 | `QualityVector`, `CapabilityGap`, `PriceQuote`, `ExperienceFinding` | תקציב חזותי אינו עוקף gate היסטורי; מדד לא נמדד נשאר null ולא ציון מומצא. | `capabilities/economy_deliver/investments/` |
| `build.settlement` (service) | קבלה, reconciliation וסגירת עלות ספק מול תוצר ו־quote. | `economy_provider` · IMPLEMENT · M3 | `CapabilityResult`, `AcceptedQuote`, `ArtifactReceipt` | מחיר מוסכם אינו עולה בשל חריגת ספק; סטטוס לא ודאי נשאר reconcile עד בדיקה. | `capabilities/economy_deliver/settlement/` |
| `build.deliver_adapter` (service) | מתאם פרוטוקול Deliver אמיתי מאחורי חוזה ספק קיים ללא זליגת internals למשחק. | `economy_provider` · IMPLEMENT · M6 | `CapabilityRequest`, `AcceptedQuote`, `CapabilityResult`, `SettlementReceipt` | conformance ותקלות נבדקים מול פרוטוקול שנלכד בפועל; provider מקומי וחיצוני משתמשים באותו builder. | `capabilities/economy_deliver/deliver_adapter/` |

### קונטקסט וניתוב משימות — 5 טיפוסים

קונטקסט: `context/game/domains/context_orchestration/DOMAIN.md` + כרטיס התפקיד. הממשקים בטבלה הם שמות גבול מוצעים; TaskSlice חייב לנעול חוזה גרסתי לפני מימוש.

| LegoId וסוג | מה בונים | כותב · פרופיל · שלב | ממשקי תלות | קבלה | יעד תוצר |
|---|---|---|---|---|---|
| `context.policy` (service) | רישום בעלות, הרשאות ומרחבי הקשר עם חסימה לפני דירוג תוצאות. | `context_router` · IMPLEMENT · M1 | `DomainRegistry`, `TaskScope`, `ScopeGrant` | בקשת טנק אינה קוראת מסמכי צי גם אם יש מילים משותפות; בעלות לא ידועה נכשלת סגור. | `capabilities/context_orchestration/policies/` |
| `context.retrieval` (service) | בחירת חבילת הקשר מצומצמת ומניפסט מקורות לגרסת משימה. | `context_router` · IMPLEMENT · M1 | `ContextPolicy`, `ContextIndex`, `ScopeGrant` | מסמך אסור אינו נכנס לסיכום או ranking; הרחבה דורשת החלטה רשומה ונפרדת. | `capabilities/context_orchestration/retrieval/` |
| `context.resolver` (service) | פירוק חוסרים ליכולות מוכנות לפי תלות, חשיבות, תקציב ו־deadline. | `context_router` · IMPLEMENT · M1 | `CapabilityRegistry`, `CapabilityGap`, `CapabilityLock`, `TaskScope` | אין שרשרת NEXT קשיחה; מחזור תלות מגיע ל־fixture, גרסה קודמת או blocker תחום. | `capabilities/context_orchestration/resolver/` |
| `context.handoff` (service) | מסירת עבודה עם תפקיד, read/write scope, חוזים, ראיות ותוצאות בדיקה. | `context_router` · IMPLEMENT · M1 | `ContextManifest`, `ArtifactReceipt`, `ContractLock`, `ScopeGrant` | תוצר עובר עם חוסרים וגרסאות; מסירה אינה מעניקה גישה טרנזיטיבית לתחום שלם. | `capabilities/context_orchestration/handoffs/` |
| `build.episode_builder` (service) | הרכבת דרישת אפיזודה למניפסט נעול דרך חוסרים, בקשות יכולת וקבלות ביקורת. | `context_router` · IMPLEMENT · M3 | `EpisodeIntent`, `CapabilityRegistry`, `CapabilityResult`, `EvidenceSnapshot`, `AssetManifest`, `ValidationReceipt` | אפיזודה נוצרת מנתונים ויכולות מותקנות; העדר רכיב חובה מחזיר CapabilityGap ולא הצלחה מדומה. | `capabilities/context_orchestration/episode_builder/` |

## 14. כל 31 כתובות הבעלות — מודל וכרטיס קונטקסט

הכרטיסים הבאים קיימים בתיקיית העבודה. פרופיל שורה יכול לחדד את מודל המשימה; הבעלים נשאר אחד. לפני שיגור המנהל רושם איזה מודל באמת זמין ובאיזה effort הוא הופעל.

| בעלים | מספר טיפוסים | מודל ברירת מחדל | חלופה זמינה כאן | כרטיס קונטקסט מדויק |
|---|---:|---|---|---|
| `evidence_sources` | 3 | `claude-opus-5-5` / high | `gpt-6-astra` / high | `context/game/domains/historical_evidence/roles/evidence_sources.md` |
| `evidence_claims` | 3 | `claude-opus-5-5` / high | `gpt-6-astra` / high | `context/game/domains/historical_evidence/roles/evidence_claims.md` |
| `terrain_world` | 16 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/geospatial_temporal/roles/terrain_world.md` |
| `temporal_world` | 3 | `gpt-6-astra` / high | `gpt-6-astra` / high | `context/game/domains/geospatial_temporal/roles/temporal_world.md` |
| `ground_powertrain` | 8 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/ground_vehicles/roles/ground_powertrain.md` |
| `ground_platform` | 8 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/ground_vehicles/roles/ground_platform.md` |
| `weapons_ballistics` | 13 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/weapons_effects/roles/weapons_ballistics.md` |
| `weapons_damage` | 5 | `gpt-6-astra` / high | `gpt-6-astra` / high | `context/game/domains/weapons_effects/roles/weapons_damage.md` |
| `infantry_actions` | 5 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/infantry/roles/infantry_actions.md` |
| `infantry_casualty` | 3 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/infantry/roles/infantry_casualty.md` |
| `aviation_platform` | 4 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/aviation/roles/aviation_platform.md` |
| `naval_platform` | 4 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/naval/roles/naval_platform.md` |
| `logistics_supply` | 4 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/logistics/roles/logistics_supply.md` |
| `logistics_maintenance` | 2 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/logistics/roles/logistics_maintenance.md` |
| `command_structure` | 3 | `claude-opus-5-5` / high | `gpt-6-astra` / high | `context/game/domains/command_organization/roles/command_structure.md` |
| `command_signals` | 2 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/command_organization/roles/command_signals.md` |
| `character_identity` | 2 | `claude-sonnet-5` / high | `gpt-5.6-sol` / high | `context/game/domains/characters/roles/character_identity.md` |
| `character_memory` | 2 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/characters/roles/character_memory.md` |
| `character_social` | 3 | `claude-sonnet-5` / high | `gpt-5.6-sol` / high | `context/game/domains/characters/roles/character_social.md` |
| `runtime_core` | 7 | `gpt-6-astra` / high | `gpt-6-astra` / high | `context/game/domains/simulation_runtime/roles/runtime_core.md` |
| `runtime_continuity` | 4 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/simulation_runtime/roles/runtime_continuity.md` |
| `experience_loop` | 13 | `claude-sonnet-5` / high | `gpt-5.6-sol` / high | `context/game/domains/experience_design/roles/experience_loop.md` |
| `experience_interface` | 6 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/experience_design/roles/experience_interface.md` |
| `weather_system` | 7 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/weather/roles/weather_system.md` |
| `assets_visual` | 8 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/asset_pipeline/roles/assets_visual.md` |
| `assets_motion` | 2 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/asset_pipeline/roles/assets_motion.md` |
| `assets_audio` | 2 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/asset_pipeline/roles/assets_audio.md` |
| `ai_perception` | 3 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/ai_navigation/roles/ai_perception.md` |
| `ai_decision` | 3 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/ai_navigation/roles/ai_decision.md` |
| `economy_provider` | 5 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/economy_deliver/roles/economy_provider.md` |
| `context_router` | 5 | `gpt-6-sol` / high | `gpt-5.6-sol` / high | `context/game/domains/context_orchestration/roles/context_router.md` |

## 15. הודעות מוכנות להעברה

לפתיחה, העבר את ההודעה הבאה ל־Astra Root עם הקובץ הזה כ־index:

```text
פעל לפי docs/game/LEGO_BUILD_CATALOG_HE.md והמרשם המקושר.
התחל ב־B00, ב־B03 ובסקירת הנכסים בלבד מתוך B07, עד שלושה עובדים לצד root.
לכל worker בחר תפקיד אחד, LegoIds, קובצי קריאה/כתיבה ו־ContractLock.
שלח רק חמש שכבות ההקשר של המשימה; אין להעביר את כל המפרט לכל worker.
בצע ביקורת חוזים לפני מימוש תלוי. אחריה התקדם ל־B01/B02/B04.
השתמש במודל הזמין שהוגדר בחבילה, ורשום fallback בפועל.
אל תממש מראש את כל הקטלוג. בנה fixtures קטנים ושימוש חוזר בשתי תצורות.
שמור על משחקיות, אנשים, פעילות שקטה והפרדת input/presentation לקראת VR.
החזר תוצרים, בדיקות אמיתיות, חוסרים וסטטוס שערי קבלה.
```

לסוכן ביצוע מעבירים את BRIEF הרלוונטי, ובוחרים את קובצי התפקיד שלו מתוכו:

| חבילה | קובץ להעברה | תלויות לפני מימוש |
|---|---|---|
| B00 — חוזים משותפים ו־host קטן | [BRIEF](../../context/game/build_packets/B00/BRIEF.md) | אין |
| B01 — טנק ורכב כהרכבה חוזרת | [BRIEF](../../context/game/build_packets/B01/BRIEF.md) | B00 |
| B02 — נשק, פעולות ירי ואפקטים | [BRIEF](../../context/game/build_packets/B02/BRIEF.md) | B00 |
| B03 — מחקר דגם וראיות היסטוריות | [BRIEF](../../context/game/build_packets/B03/BRIEF.md) | אין |
| B04 — מזג אוויר, קרקע והשפעות | [BRIEF](../../context/game/build_packets/B04/BRIEF.md) | B00 |
| B05 — תבנית קרב ופעילויות מעניינות | [BRIEF](../../context/game/build_packets/B05/BRIEF.md) | B00 |
| B06 — אנשים, יחידה ותפיסה | [BRIEF](../../context/game/build_packets/B06/BRIEF.md) | B00 |
| B07 — נכסים, ריג, קול וכלי preview | [BRIEF](../../context/game/build_packets/B07/BRIEF.md) | B00 |
| B08 — גוף, מצלמה, קלט ומסלול VR | [BRIEF](../../context/game/build_packets/B08/BRIEF.md) | B00 |
| B09 — שילוב, שמירה וביקורת עצמאית | [BRIEF](../../context/game/build_packets/B09/BRIEF.md) | B00 |

### גרף השיגור המפורט

התלויות להלן הן לתוצר תחום או לשלב עיצוב/חוזה. קבלת החוויה המשולבת נשארת בסוף. כל שורה מקבלת רק את כרטיס בעל התפקיד שלה ואת ה־LegoIds שלה במרשם. משימות עם אותו כותב וקבצים משותפים מסתדרות בתור גם אם אין ביניהן תלות טכנית.

| TaskSlice | בעלים יחיד | ממתין ל־ | תחום התוצר |
|---|---|---|---|
| `B00/contracts` | `runtime_core` | אין | קודם חוזים ו־fixtures; בעלים אחרים מקבלים API נעול בלבד. |
| `B07/inventory` | `assets_visual` | אין | מלאי נכסים/כלים/רישיונות בלבד; אין תלות בחוזים לבירור זה. |
| `B01/ground_platform` | `ground_platform` | `B00/contracts`, `B01/ground_powertrain` | `equipment.chassis`, `equipment.armor_plate`, `equipment.turret`, `equipment.fuel_tank`, `equipment.crew_station`, `equipment.ground_vehicle`, `equipment.access_port`, `equipment.stowage` |
| `B01/ground_powertrain` | `ground_powertrain` | `B00/contracts` | `equipment.engine`, `equipment.transmission`, `equipment.wheel`, `equipment.track`, `equipment.suspension`, `mobility.tracked`, `mobility.wheeled` |
| `B02/weapons_ballistics` | `weapons_ballistics` | `B00/contracts` | `equipment.gun`, `equipment.projectile`, `equipment.optic`, `weapons.ammunition_compatibility`, `weapons.firing_reload`, `weapons.ballistics`, `equipment.weapon_action`, `equipment.weapon_mount`, `equipment.barrel`, `equipment.breech`, `equipment.feed_system`, `equipment.weapon_stock` |
| `B02/weapons_damage` | `weapons_damage` | `B00/contracts` | `effects.armor_interaction`, `effects.fire`, `effects.suppression`, `effects.obscurant` |
| `B03/evidence_sources` | `evidence_sources` | אין | `evidence.source`, `evidence.locator`, `evidence.snapshot` |
| `B03/evidence_claims` | `evidence_claims` | `B03/evidence_sources` | `evidence.claim`, `evidence.contradiction`, `evidence.reconstruction` |
| `B04/weather_system` | `weather_system` | `B00/contracts` | `weather.sample`, `weather.timeline`, `weather.precipitation`, `weather.wind`, `weather.visibility_cloud`, `weather.thermal`, `weather.effects` |
| `B04/terrain_world` | `terrain_world` | `B00/contracts` | `world.terrain`, `world.surface_material`, `world.surface_state` |
| `B05/experience_loop` | `experience_loop` | `B00/contracts` | עיצוב תבניות/פעילויות ו־data fixtures תחילה; acceptance אינטגרטיבי נבדק ב־B09/final_integration, לא תנאי לסיום שלב העיצוב. |
| `B06/infantry_actions` | `infantry_actions` | `B00/contracts` | `actor.human`, `infantry.locomotion`, `infantry.carried_equipment` |
| `B06/infantry_casualty` | `infantry_casualty` | `B00/contracts` | `infantry.condition`, `infantry.injury`, `infantry.care` |
| `B06/character_identity` | `character_identity` | `B00/contracts` | `character.identity` |
| `B06/character_memory` | `character_memory` | `B00/contracts`, `B06/character_identity`, `B00/runtime_followup` | `character.memory`, `character.knowledge` |
| `B06/character_social` | `character_social` | `B00/contracts`, `B06/character_memory`, `B05/experience_loop` | שיחה מוגבלת ומתוסרטת בלבד בפרוסה; אין חובה ל־LLM בזמן משחק. |
| `B06/ai_perception` | `ai_perception` | `B00/contracts`, `B04/weather_system`, `B04/terrain_world`, `B00/runtime_followup` | `perception.vision`, `perception.hearing`, `perception.observation` |
| `B06/ai_decision` | `ai_decision` | `B00/contracts`, `B06/ai_perception`, `B06/infantry_actions` | `ai.cognition`, `ai.navigation` |
| `B06/command_signals` | `command_signals` | `B00/contracts`, `B06/command_structure` | `command.communications` |
| `B06/command_structure` | `command_structure` | `B00/contracts` | `command.organization`, `command.authority`, `command.orders` |
| `B06/logistics_supply` | `logistics_supply` | `B00/contracts` | `logistics.stock`, `logistics.transfer`, `logistics.resource_definition` |
| `B07/assets_visual` | `assets_visual` | `B00/contracts`, `B07/inventory`, `B01/ground_platform`, `B02/weapons_ballistics` | `asset.mesh`, `asset.material`, `asset.import_manifest`, `asset.visual_binding`, `asset.vfx`, `asset.environment_light`, `asset.decals`, `asset.catalog_preview` |
| `B07/assets_motion` | `assets_motion` | `B00/contracts`, `B07/assets_visual`, `B06/infantry_actions` | `asset.rig`, `asset.animation` |
| `B07/assets_audio` | `assets_audio` | `B00/contracts` | `asset.spatial_audio`, `asset.voice_subtitles` |
| `B08/experience_interface` | `experience_interface` | `B00/contracts`, `B00/runtime_followup`, `B06/infantry_actions` | `player.desktop_input`, `player.vr_boundary`, `player.comfort`, `player.interface`, `player.body` |
| `B00/runtime_followup` | `runtime_core` | `B00/contracts`, `B05/experience_loop` | משימת B05 התלויה היא עיצוב data/fixtures בלבד; היא אינה ממתינה ל־evaluator. |
| `B09/continuity_seam` | `runtime_continuity` | `B00/contracts` | snapshot וחוזה שמירה מוקדם; רכיבים משתמשים ב־fixture לפני שילוב מלא. |
| `B09/final_integration` | `runtime_continuity` | `B00/contracts`, `B07/inventory`, `B01/ground_platform`, `B01/ground_powertrain`, `B02/weapons_ballistics`, `B02/weapons_damage`, `B03/evidence_sources`, `B03/evidence_claims`, `B04/weather_system`, `B04/terrain_world`, `B05/experience_loop`, `B06/infantry_actions`, `B06/infantry_casualty`, `B06/character_identity`, `B06/character_memory`, `B06/character_social`, `B06/ai_perception`, `B06/ai_decision`, `B06/command_signals`, `B06/command_structure`, `B06/logistics_supply`, `B07/assets_visual`, `B07/assets_motion`, `B07/assets_audio`, `B08/experience_interface`, `B00/runtime_followup`, `B09/continuity_seam` | כותב רק continuity; מבקש תיקוני מודולים מבעליהם; reviewers עצמאיים ושער חוויה אנושי לפני promotion. |

בדיקת שלמות הקטלוג וחידוש טבלאותיו: `python3 tools/game/render_lego_catalog.py`. הבדיקה בודקת IDs, בעלויות, נתיבי קונטקסט, הפניות חבילות ופרופילים; היא אינה מריצה משחק או מאמתת עובדות היסטוריות.
<!-- GENERATED_CATALOG_END -->

## מקורות מבניים וביקורת

[הרישום המכני](LEGO_OWNERSHIP_REGISTRY.json) הוא מקור טבלאות הרכיבים והבעלויות המופקות במסמך זה. שינוי רשומה מחייב חידוש הטבלאות ובדיקת חבילות השיגור. הוא אינו מחליף את חוזי `game/contracts.py` או מכריז על assets כקיימים. [פירוט עץ וקונטקסט](planning/AGENT_TREE_CONTEXT_HE.md) מרחיב את הניהול. [ארכיטקטורת המשחק](MASTER_ARCHITECTURE.md) נשארת נקודת הכניסה להחלטות המערכת.

[סיכום הביקורת ותיקוניה](reviews/LEGO_CATALOG_REVIEW.md) ו־[תוצאות בדיקת שלמות הקטלוג](reviews/LEGO_CATALOG_CHECK.json) מציינים מה אומת בתכנון ומה נשאר לבנייה ולבדיקה בפועל.
