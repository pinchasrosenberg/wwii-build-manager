DOMUS_FLAVIA_SOURCES = [
    'Domus Flavia על הפלטין (נבנה בידי רבירוס לדומיטיאנוס, 92 לספירה): תוכנית לפי Lanciani, Forma Urbis Romae, ולפי סקרי המכון הגרמני לארכאולוגיה (Wulf-Rheidt)',
    'מידות החדרים בקירוב: אולם המלך כ־30×38 מ׳, הבזיליקה כ־20×31 מ׳ עם אפסיס, הפריסטיל כ־55×50 מ׳ עם מזרקה־מבוך מתומנת, חדר האוכל (Coenatio Iovis) כ־29×31 מ׳ עם אפסיס',
    'חיפוי שיש צבעוני (ג׳אלו אנטיקו, פבונאצטו, פורפיר), רצפות opus sectile ועמודים מעוטרים — לפי ממצאי החפירה; הפרטים הצבעוניים המדויקים בחדרים הם שחזור משוער',
]

DOMUS_FLAVIA_ROOMS = [
    {'id': 'aula_regia', 'name': 'אולם המלך (Aula Regia)', 'cx': 0.0, 'cz': 0.0, 'w': 30.0, 'd': 38.0, 'h': 16.0, 'apse': 'n',
     'doors': [{'wall': 's', 'pos': 0.0, 'width': 5.0, 'exit': True}, {'wall': 'w', 'pos': 4.0, 'width': 3.4}, {'wall': 'e', 'pos': 4.0, 'width': 3.4}, {'wall': 'n', 'pos': 9.0, 'width': 3.4}]},
    {'id': 'basilica', 'name': 'הבזיליקה (אולם המשפט)', 'cx': -25.4, 'cz': -3.5, 'w': 20.0, 'd': 31.0, 'h': 13.0, 'apse': 'n',
     'doors': [{'wall': 'e', 'pos': 7.5, 'width': 3.4}]},
    {'id': 'lararium', 'name': 'הלרריום (מקדש אלי הבית)', 'cx': 22.4, 'cz': -3.5, 'w': 14.0, 'd': 31.0, 'h': 10.0,
     'doors': [{'wall': 'w', 'pos': -7.5, 'width': 3.4}]},
    {'id': 'fauces', 'name': 'המעבר לפריסטיל', 'cx': 9.0, 'cz': -22.9, 'w': 5.0, 'd': 7.0, 'h': 6.0,
     'doors': [{'wall': 's', 'pos': 0.0, 'width': 3.4}, {'wall': 'n', 'pos': 0.0, 'width': 3.4}]},
    {'id': 'peristyle', 'name': 'הפריסטיל — החצר עם המזרקה המתומנת', 'cx': 0.0, 'cz': -52.8, 'w': 56.0, 'd': 52.0, 'h': 7.0, 'open': True,
     'doors': [{'wall': 's', 'pos': 9.0, 'width': 3.4}, {'wall': 'n', 'pos': 0.0, 'width': 5.0}]},
    {'id': 'triclinium', 'name': 'חדר המשתאות (Coenatio Iovis)', 'cx': 0.0, 'cz': -94.7, 'w': 29.0, 'd': 31.0, 'h': 14.0, 'apse': 'n',
     'doors': [{'wall': 's', 'pos': 0.0, 'width': 5.0}]},
]

GIALLO = '#c9a24a'
PAVONAZZETTO = '#e2d8cc'
PORPHYRY = '#6e2433'
SERPENTINE = '#3f5f3f'


def item(kind, **params):
    return {'kind': kind, **params}


DOMUS_FLAVIA_DESIGNS = {
    'fauces': {
        'floor': {'material': 'marble', 'color': '#e8e4da'}, 'walls': {'material': 'marble_revetment', 'color': PAVONAZZETTO},
        'ceiling': {'style': 'vaulted', 'color': '#d9cfb8'}, 'windows': {'style': 'arched', 'size': 'small', 'count': 0, 'color': '#f2e2b8', 'stained': False},
        'light': {'tone': 'warm', 'intensity': 0.8}, 'items': [], 'notes': 'מעבר מקורה בין אולם המלך לחצר.',
    },
    'aula_regia': {
        'floor': {'material': 'opus_sectile', 'color': '#e4ddcc'}, 'walls': {'material': 'marble_revetment', 'color': GIALLO},
        'ceiling': {'style': 'coffered', 'color': '#d9cfb8'}, 'windows': {'style': 'arched', 'size': 'large', 'count': 3, 'color': '#f2e2b8', 'stained': False},
        'light': {'tone': 'warm', 'intensity': 1.5},
        'items': [item('throne', color='#c9a227'), item('column', count=12, color=PAVONAZZETTO), item('statue', count=8, color='#b9a98a', h=4.2), item('rug', color=PORPHYRY), item('candelabra', count=6)],
        'notes': 'כאן ישב הקיסר בקבלת קהל. בנישות שלאורך הקירות עמדו פסלי ענק מבזלת ירוקה, והעמודים היו מפבונאצטו ומג׳אלו אנטיקו.',
    },
    'basilica': {
        'floor': {'material': 'opus_sectile', 'color': '#ded6c4'}, 'walls': {'material': 'marble_revetment', 'color': PAVONAZZETTO},
        'ceiling': {'style': 'coffered', 'color': '#d9cfb8'}, 'windows': {'style': 'arched', 'size': 'normal', 'count': 2, 'color': '#f2e2b8', 'stained': False},
        'light': {'tone': 'warm', 'intensity': 1.2},
        'items': [item('throne', color='#a8862e'), item('column', count=8, color=GIALLO), item('table', color='#6b4423')],
        'notes': 'אולם השיפוט של הקיסר, עם שתי שורות עמודים ואפסיס שבו ישב השופט.',
    },
    'lararium': {
        'floor': {'material': 'marble', 'color': '#e8e4da'}, 'walls': {'material': 'marble_revetment', 'color': SERPENTINE},
        'ceiling': {'style': 'vaulted', 'color': '#d9cfb8'}, 'windows': {'style': 'arched', 'size': 'small', 'count': 1, 'color': '#f2e2b8', 'stained': False},
        'light': {'tone': 'warm', 'intensity': 1.0},
        'items': [item('statue', count=4, color='#d8cfbe', h=2.6), item('candelabra', count=4), item('fountain', color='#e4ddcc')],
        'notes': 'מקדש פרטי לאלי הבית ולגניוס של הקיסר.',
    },
    'peristyle': {
        'floor': {'material': 'marble', 'color': '#e8e4da'}, 'walls': {'material': 'plaster', 'color': '#c98d5a'},
        'ceiling': {'style': 'open', 'color': '#ffffff'}, 'windows': {'style': 'arched', 'size': 'normal', 'count': 0, 'color': '#f2e2b8', 'stained': False},
        'light': {'tone': 'neutral', 'intensity': 1.6},
        'items': [item('fountain_oct', color='#e4ddcc'), item('column', count=20, color='#e8e2d4'), item('plant', count=12), item('statue', count=4, color='#d8cfbe', h=2.4)],
        'notes': 'חצר פתוחה מוקפת סטווים. במרכזה מזרקה־מבוך מתומנת גדולה, שעדיין נראית בחפירות.',
    },
    'triclinium': {
        'floor': {'material': 'opus_sectile', 'color': '#e4ddcc'}, 'walls': {'material': 'marble_revetment', 'color': PORPHYRY},
        'ceiling': {'style': 'coffered', 'color': '#d9cfb8'}, 'windows': {'style': 'arched', 'size': 'large', 'count': 2, 'color': '#f2e2b8', 'stained': False},
        'light': {'tone': 'warm', 'intensity': 1.4},
        'items': [item('couch', count=9, color='#7a1f2b'), item('table', color='#6b4423'), item('column', count=8, color=GIALLO), item('chandelier', count=2), item('statue', count=2, color='#d8cfbe', h=3.0)],
        'notes': 'חדר המשתאות של יופיטר, עם אפסיס לקיסר. בצדדיו היו נימפיאונים (מזרקות), ותחת הרצפה הייתה מערכת חימום (היפוקאוסט).',
    },
}
