# runtime_core

תחום: `simulation_runtime`. פרופיל: `DEEP`.
ברירת מחדל: `gpt-6-astra` / `high`. חלופה בסביבה הנוכחית: `gpt-6-astra` / `high`.

זהו כרטיס תפקיד, לא agent מותקן. מודל במשימה מסוימת יכול להשתנות לפי פרופיל הרשומה; הבעלות אינה משתנה. אל תקרא את מלוא מסמך הארכיטקטורה או ארכיון המקורות כברירת מחדל.

## מה בבעלותך
- `runtime.ecs` — רישום רכיבים וזהויות עם בעלות כתיבה מפורשת ומבטים מורשים.
- `runtime.schedule` — תזמון tick קבוע, סדר מערכות ושעונים מקומיים מוכרזים.
- `runtime.physics_port` — גבול physics/navigation המקבל פקודות ומחזיר תוצאות מאושרות מה־backend הנעול.
- `runtime.events` — סדר אירועים, סיבות, ייחודיות ו־RNG בתחום determinism מפורש.
- `runtime.actor_projection` — סינון מצב עולם למבט שחקן או NPC על בסיס מידע שנמסר בלבד.
- `runtime.episode_loader` — טעינת EpisodeSpec, רכיבים ונכסים לפי גרסאות, hashes והתקנות מורשות.
- `runtime.battle_evaluator` — הערכת תנאים ושלבי תבנית נתונית בסדר אירועים מוגדר, בלי קוד אפיזודה שרירותי.

## חבילת הביצוע הנדרשת
1. Global invariants + DOMAIN.md + כרטיס זה.
2. TaskSlice עם IDs נבחרים, יעד, קובצי קריאה/כתיבה מדויקים וקבלה.
3. ContractLock עם schema/semantics/version/hash ו־fixture לכל ממשק נצרך.
4. EvidenceSlice מוגבל לדגם/מקום/זמן, או fixture סינתטי מסומן.
5. תקציב context וביצוע, מצב בסיס והוראות handoff.

## תוצר והסלמה
החזר קוד/נתונים/manifest לפי המשימה, בדיקות עם תוצאות בפועל, פערים והפניות למקורות ול־context ששימשו. אל תדווח על סצנת משחק, נכס, בדיקת headset או historical review שלא בוצעו. שינוי אצל בעלים אחר מוחזר כבקשת שינוי; שינוי בחוזה משותף מתואם עם runtime_core/root.
