# B05 — תבנית קרב ופעילויות מעניינות

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `claude-sonnet-5` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `DESIGN`. בעלים: `experience_loop`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
כתוב תבנית סיור/הגנה קטנה ותבנית שנייה שמורכבות מאותן פעולות. ספק תפקיד שחקן ברור, בן יחידה מוכר, פעילות שקטה ובחירה מקומית. תכנן לפי מה שכדאי לחוות, עם היסטוריה כגבול.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/experience_design/DOMAIN.md`
- `context/game/domains/experience_design/roles/experience_loop.md`
- `docs/game/EXPERIENCE_DESIGN.md`
- `docs/game/EPISODE_SCHEMA.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `battle.template`
- `battle.objective`
- `battle.condition`
- `battle.force_role`
- `battle.deployment`
- `battle.phase`
- `battle.anchor_policy`
- `battle.outcome`
- `battle.difficulty_overlay`
- `experience.interaction`
- `experience.activity`
- `experience.pacing`
- `experience.profiles`

## תוצרים
- תבניות data ו־activity recipes; אפיון תנאים למימוש B00/runtime.battle_evaluator
- רשימת feedback/player affordances, branches מותרים ו־anchor conflicts
- תוכנית playtest ותצפיות נדרשות; כל שמות היסטוריים חסרי מקור מסומנים fixture

## קבלה
- לא נדרש script מיוחד לכל Episode; אין eval בנתונים
- שקט כולל אפשרות משמעותית/ציפייה/יחס; לא מילוי זמן מלאכותי
- אי הצלחה שומרת אובדן ומלאי; העוגן אינו מחייב teleport או החייאה
- מבחן אנושי בודק הבנת תפקיד ורצון להמשיך; ביקורת LLM אינה מחליפה אותו

## כתיבה וגבולות
רק experience_design data; runtime_core כותב evaluator, command/AI ממשיכים להיות בעליהם של ארגון והחלטות.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
