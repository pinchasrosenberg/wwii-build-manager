# B08 — גוף, מצלמה, קלט ומסלול VR

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-sol` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `IMPLEMENT`. בעלים: `experience_interface`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
בנה embodiment playable ב־desktop דרך semantic actions עם הפרדה בין גוף/ראש/ידיים. הכן mock tracked pose וממשק OpenXR, נגישות ומעבר למושב רכב. שמור את חוויית המשחק העיקרית קריאה ללא מסך מידע.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/experience_design/DOMAIN.md`
- `context/game/domains/experience_design/roles/experience_interface.md`
- `docs/game/VR_READINESS.md`
- `docs/game/EXPERIENCE_DESIGN.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `player.desktop_input`
- `player.vr_boundary`
- `player.comfort`
- `player.interface`
- `player.body`

## תוצרים
- מתאם desktop, action validator integration, camera/body/hand separation
- ממשק tracking loss/pose ו־seated/standing; checklist ניסוי מכשיר
- UI/כתוביות/הוראות עם RTL, contrast ו־remapping

## קבלה
- אותה פעולה דרך replay ו־desktop נותנת אותה תוצאה
- אין שליטה כפויה בראש ה־VR; כניסה/יציאה מרכב לא מכפילה avatar
- synthetic tracking אינו דיווח על headset נתמך; מדידות נוחות/קצב רק על מכשיר

## כתיבה וגבולות
נתיבי experience_interface בלבד; אין תלות gameplay ב־mouse position או שינוי core בשביל כל אמצעי קלט.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
