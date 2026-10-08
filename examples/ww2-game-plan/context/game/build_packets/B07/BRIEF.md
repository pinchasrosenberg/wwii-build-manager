# B07 — נכסים, ריג, קול וכלי preview

מצב: חבילת שיגור מוכנה לתכנון ובחירת TaskSlice; אינה הרצה ואינה הרשאה לקריאת כל הדומיינים.

מודל מומלץ: `gpt-6-sol` / `high`. זמין בסביבה זו: `gpt-5.6-sol` / `high`.
פרופיל: `VISUAL`. בעלים: `assets_visual`, `assets_motion`, `assets_audio`.
תלויות לפני מימוש: B00.

## הודעה להעברה לסוכן
ראשית רשום נכסים/כלים קיימים, פורמטים ורישיונות. לאחר החוזים חבר asset אחד לדגם/fixture, סצנת preview, אחיזות ואנימציית פעולה אחת. ודא שהרכב/נשק הנראה הוא אותו variant שמסומלץ.

אתה פועל כבעל תפקיד אחד מתוך הרשימה. אם טרם נבחר תת־תפקיד, הצע חלוקה וקח רק את החלק שבבעלותך; אין לקחת בעלות על כולם. לפני שינוי קוד הפק TaskSlice עם LegoIds נבחרים, נתיבי קריאה/כתיבה, ContractLock, evidence refs וקריטריוני קבלה. לאחר הקפאת התלויות המשך במימוש התחום שהוקצה. כל הנחות fixture מסומנות synthetic. אין hardcoding של קרב או דגם ואין תלות ב־Deliver בתוך tick.

## קובצי קונטקסט לפתיחה
טען רק את קובצי התפקיד שלך; קובצי תפקידים אחרים ברשימה מיועדים לתת־משימות נפרדות. מסמכי רקע גדולים נבחרים בקטעים רלוונטיים, לא נטענים כברירת מחדל בשלמותם.
- `context/game/global/INVARIANTS.md`
- `context/game/domains/asset_pipeline/DOMAIN.md`
- `context/game/domains/asset_pipeline/roles/assets_visual.md`
- `context/game/domains/asset_pipeline/roles/assets_motion.md`
- `context/game/domains/asset_pipeline/roles/assets_audio.md`
- `docs/game/VR_READINESS.md`
- מתוך `docs/game/LEGO_OWNERSHIP_REGISTRY.json`: רק הרשומות המפורטות להלן וה־model profile שנבחר.
- מתוך `context/game/interfaces/README.md`: בקש את חוזי התלות הגרסתיים הדרושים; הרשימה היא אינדקס הצעות, לא API שכבר קיים.
- ראיות דגם/מקום/זמן יצורפו על ידי B03 כאשר יש שימוש היסטורי; אין מקור היסטורי בחבילת פתיחה זו.

## רשימת רכיבים לבחירת TaskSlice
- `asset.mesh`
- `asset.material`
- `asset.import_manifest`
- `asset.rig`
- `asset.animation`
- `asset.spatial_audio`
- `asset.voice_subtitles`
- `asset.visual_binding`
- `asset.vfx`
- `asset.environment_light`
- `asset.decals`
- `asset.catalog_preview`

## תוצרים
- מקור editable ככל שרישיון מתיר, glTF/GLB או משאב Godot, textures, manifest ו־hash
- ריג/anchors/action mapping בנפרד מגאומטריה; audio cues וקבצים מורשים בנפרד
- preview וקובץ מגבלות/placeholder; אין טענה שנוצר 3D רק מפני שנכתבה תמונת concept

## קבלה
- יחידות/צירים/scale/VariantId נכונים; שינוי LOD שומר silhouette חיוני
- animation/VFX/audio מקבלים אירוע מוסמך; לא צורכים ammo או קובעים hit
- נכס בלי זכויות שימוש מתאימות נשאר gap; VR stereo/device gate נפרד

## כתיבה וגבולות
asset_pipeline בלבד; לכל mesh/rig/audio owner קבצים נפרדים. אם כלי 3D אינו זמין אפשר להחזיר pipeline/placeholder מפורש, לא asset גמור.

## handoff מחייב
החזר changed_paths, artifact/version/hash, contracts_used, evidence_used, tests_run/results, untested_limits, gaps, next_dependency. ציין את המודל וה־effort שבפועל הופעלו, לא רק את ההמלצה. אין calls בתשלום ללא מסגרת quote/budget החלה על המשימה.
