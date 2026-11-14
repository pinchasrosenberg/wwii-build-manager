import re

COLORS = {
    'אדום': '#b3382c', 'אדומים': '#b3382c', 'אדומות': '#b3382c', 'red': '#b3382c',
    'כחול': '#2f5d9e', 'כחולים': '#2f5d9e', 'כחולות': '#2f5d9e', 'blue': '#2f5d9e',
    'תכלת': '#5fb7d9', 'turquoise': '#3fb6b2',
    'לבן': '#ece8dc', 'לבנים': '#ece8dc', 'לבנות': '#ece8dc', 'white': '#ece8dc',
    'שחור': '#25252b', 'שחורים': '#25252b', 'שחורות': '#25252b', 'black': '#25252b',
    'אפור': '#8a8d93', 'אפורים': '#8a8d93', 'אפורות': '#8a8d93', 'gray': '#8a8d93', 'grey': '#8a8d93',
    'זהב': '#d4a93a', 'זהוב': '#d4a93a', 'זהובים': '#d4a93a', 'זהובות': '#d4a93a', 'gold': '#d4a93a', 'golden': '#d4a93a',
    'ירוק': '#3f7a4a', 'ירוקים': '#3f7a4a', 'ירוקות': '#3f7a4a', 'green': '#3f7a4a',
    'סגול': '#6a4a9c', 'סגולים': '#6a4a9c', 'סגולות': '#6a4a9c', 'purple': '#6a4a9c',
    'כתום': '#d9772b', 'כתומים': '#d9772b', 'כתומות': '#d9772b', 'orange': '#d9772b',
    'צהוב': '#e0c243', 'צהובים': '#e0c243', 'צהובות': '#e0c243', 'yellow': '#e0c243',
    'חום': '#7a5233', 'חומים': '#7a5233', 'חומות': '#7a5233', 'brown': '#7a5233',
    'ורוד': '#d98aa6', 'ורודים': '#d98aa6', 'ורודות': '#d98aa6', 'pink': '#d98aa6',
    'בורדו': '#6e2433', 'burgundy': '#6e2433',
    'כסוף': '#b9bec7', 'כסף': '#b9bec7', 'silver': '#b9bec7',
    'בז': '#cdbb95', 'beige': '#cdbb95',
}

COLOR_NAMES = {
    '#b3382c': 'אדום', '#2f5d9e': 'כחול', '#5fb7d9': 'תכלת', '#3fb6b2': 'טורקיז', '#ece8dc': 'לבן', '#25252b': 'שחור',
    '#8a8d93': 'אפור', '#d4a93a': 'זהב', '#3f7a4a': 'ירוק', '#6a4a9c': 'סגול', '#d9772b': 'כתום', '#e0c243': 'צהוב',
    '#7a5233': 'חום', '#d98aa6': 'ורוד', '#6e2433': 'בורדו', '#b9bec7': 'כסף', '#cdbb95': 'בז׳',
}

MATERIAL_COLORS = {
    'stone': '#8d8a82', 'wood': '#8b6540', 'marble': '#e6e2d8', 'sandstone': '#c8a96b',
    'brick': '#a2553b', 'ice': '#bfe3f0', 'dark_stone': '#4a4a52', 'plaster': '#e3d9c3',
}

PREFIXES = ('וה', 'שה', 'מה', 'לה', 'בה', 'כה', 'וב', 'ול', 'ומ', 'וכ', 'ב', 'ה', 'ל', 'ו', 'מ', 'ש', 'כ')


def tokens(text):
    cleaned = re.sub(r'[֑-ׇ]', '', text.lower())
    cleaned = cleaned.replace('״', '').replace('"', '').replace('׳', '').replace("'", '')
    return re.findall(r'[\w-]+', cleaned)


def variants(token):
    stripped = [token[len(p):] for p in PREFIXES if token.startswith(p) and len(token) - len(p) >= 2]
    return [token] + stripped


NOT_PREFIXED = {'מים': ('ים',), 'בית': ('ית',), 'הר': ('ר',)}


def token_is(token, stems):
    blocked = NOT_PREFIXED.get(token, ())
    return any((v == s and s not in blocked) or (len(s) >= 4 and v.startswith(s) and s not in blocked) for v in variants(token) for s in stems)


def has_any(toks, stems):
    return any(token_is(t, stems) for t in toks)


def color_near(toks, nouns, window=1):
    hits = [i for i, t in enumerate(toks) if token_is(t, nouns)]
    found = [
        COLORS[toks[j]]
        for i in hits
        for j in list(range(i + 1, min(len(toks), i + 1 + window))) + [i - 1]
        if 0 <= j < len(toks) and toks[j] in COLORS
    ]
    return found[0] if found else None


NUMBER_WORDS = {
    'אחד': 1, 'אחת': 1, 'שני': 2, 'שתי': 2, 'שניים': 2, 'שתיים': 2, 'שלוש': 3, 'שלושה': 3, 'ארבע': 4, 'ארבעה': 4,
    'חמש': 5, 'חמישה': 5, 'שש': 6, 'שישה': 6, 'שבע': 7, 'שבעה': 7, 'שמונה': 8, 'תשע': 9, 'תשעה': 9, 'עשר': 10, 'עשרה': 10,
    'כמה': 3, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'eight': 8, 'ten': 10,
}


def count_before(toks, index, default=1):
    window = toks[max(0, index - 1):index]
    nums = [NUMBER_WORDS.get(t, int(t) if t.isdigit() else None) for t in window]
    nums = [n for n in nums if n]
    return nums[-1] if nums else default
