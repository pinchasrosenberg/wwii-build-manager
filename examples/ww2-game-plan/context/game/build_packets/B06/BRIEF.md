# B06 — אנשים, יחידה ותפיסה

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-sol` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `IMPLEMENT`. בעלים: `infantry_actions`, `infantry_casualty`, `character_identity`, `character_memory`, `character_social`, `ai_perception`, `ai_decision`, `command_signals`, `command_structure`, `logistics_supply`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
פצל למשימות קצרות ובנה כמה חברי יחידה בעלי זהות מתמשכת, הליכה, תפיסה, משימה מקומית ושיחה מתוסרטת מוגבלת. אין LLM חובה בזמן tick; memories כוללים רק אירועים שנמסרו. הקצה משימות נפרדות ל־logistics_supply עבור מלאי והעברות, ל־command_structure עבור סמכות/פקודות ול־character_memory עבור ידע. character.dialogue נבנה תחילה כשיחה מוגבלת ומתוסרטת; שיחת LLM מתמשכת היא הרחבה עתידית.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/infantry/DOMAIN.md`
- `context/game/domains/infantry/roles/infantry_actions.md`
- `context/game/domains/infantry/roles/infantry_casualty.md`
- `context/game/domains/characters/DOMAIN.md`
- `context/game/domains/characters/roles/character_identity.md`
- `context/game/domains/characters/roles/character_memory.md`
- `context/game/domains/characters/roles/character_social.md`
- `context/game/domains/ai_navigation/DOMAIN.md`
- `context/game/domains/ai_navigation/roles/ai_perception.md`
- `context/game/domains/ai_navigation/roles/ai_decision.md`
- `context/game/domains/command_organization/DOMAIN.md`
- `context/game/domains/command_organization/roles/command_signals.md`
- `context/game/domains/command_organization/roles/command_structure.md`
- `context/game/domains/logistics/DOMAIN.md`
- `context/game/domains/logistics/roles/logistics_supply.md`
- `docs/game/EXPERIENCE_DESIGN.md`
- `docs/game/SIMULATION_LOD.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `actor.human`
- `infantry.locomotion`
- `infantry.condition`
- `infantry.injury`
- `infantry.carried_equipment`
- `character.identity`
- `character.memory`
- `character.relationship`
- `perception.vision`
- `perception.hearing`
- `perception.observation`
- `ai.cognition`
- `ai.navigation`
- `command.communications`
- `infantry.care`
- `character.dialogue`
- `character.knowledge`
- `command.organization`
- `command.authority`
- `command.orders`
- `logistics.stock`
- `logistics.transfer`
- `logistics.resource_definition`

## תוצרים
- avatar/actions ותנאי אדם; identity ומצב שנשמרים
- perception→delivered observation→decision; ידיעה מתעכבת
- פעולת עזרה/שיתוף ושיחה קצרה מאושרת; social text יכול להיות משימת Sonnet נפרדת

## קבלה
- חבר מוכר נשאר אותו אדם אחרי save/יציאה מטווח; פצוע אינו חוזר לבריאות ללא תהליך
- fog/occlusion מגבילים תפיסה; NPC אינו יודע אירוע עתידי
- אין אותו state field בשתי סמכויות; identity אינו מוחזק ב־renderer

## כתיבה וגבולות
כל ריצה מקבלת בעל אחד ונתיבי אותו תפקיד בלבד; הרשימה הארוכה היא תור משימות, לא worker שקורא שמונה תחומים.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
