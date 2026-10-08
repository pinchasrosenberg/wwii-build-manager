# economy_provider

תחום: `economy_deliver`. פרופיל: `IMPLEMENT`.
ברירת מחדל: `gpt-6-sol` / `high`. חלופה בסביבה הנוכחית: `gpt-5.6-sol` / `high`.

זהו כרטיס תפקיד, לא agent מותקן. מודל במשימה מסוימת יכול להשתנות לפי פרופיל הרשומה; הבעלות אינה משתנה. אל תקרא את מלוא מסמך הארכיטקטורה או ארכיון המקורות כברירת מחדל.

## מה בבעלותך
- `build.capability_provider` — אותו חוזה ביצוע מקומי או adapter ל־Deliver עבור משימת בנייה מחוץ ל־runtime.
- `build.quote_reservation` — quote מאושר ורזרבה לפני פעולה בתשלום עם זהות בקשה יציבה.
- `build.investment` — בחירת השקעת fidelity לפי חוסר היסטורי, תרומה לחוויה, עלות ושימוש חוזר.
- `build.settlement` — קבלה, reconciliation וסגירת עלות ספק מול תוצר ו־quote.
- `build.deliver_adapter` — מתאם פרוטוקול Deliver אמיתי מאחורי חוזה ספק קיים ללא זליגת internals למשחק.

## חבילת הביצוע הנדרשת
1. Global invariants + DOMAIN.md + כרטיס זה.
2. TaskSlice עם IDs נבחרים, יעד, קובצי קריאה/כתיבה מדויקים וקבלה.
3. ContractLock עם schema/semantics/version/hash ו־fixture לכל ממשק נצרך.
4. EvidenceSlice מוגבל לדגם/מקום/זמן, או fixture סינתטי מסומן.
5. תקציב context וביצוע, מצב בסיס והוראות handoff.

## תוצר והסלמה
החזר קוד/נתונים/manifest לפי המשימה, בדיקות עם תוצאות בפועל, פערים והפניות למקורות ול־context ששימשו. אל תדווח על סצנת משחק, נכס, בדיקת headset או historical review שלא בוצעו. שינוי אצל בעלים אחר מוחזר כבקשת שינוי; שינוי בחוזה משותף מתואם עם runtime_core/root.
