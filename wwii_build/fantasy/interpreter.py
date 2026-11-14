import json
import os
import urllib.request
import zlib

from .lexicon import COLORS, MATERIAL_COLORS, color_near, count_before, has_any, tokens

OLLAMA_URL = os.environ.get('FANTASY_OLLAMA_URL', 'http://127.0.0.1:11434')
OLLAMA_MODEL = os.environ.get('FANTASY_LLM', 'qwen2.5:14b')

TERRAIN_KINDS = ('sharp_mountains', 'mountains', 'plains', 'valley', 'islands', 'coast', 'canyon', 'desert', 'cliff_port')
PRECIP = ('none', 'snow', 'rain')
VEGETATION = ('temperate', 'alpine', 'tropical', 'desert', 'none')
MATERIALS = tuple(MATERIAL_COLORS)
ROOFS = ('pointed', 'dome', 'flat', 'curved', 'gable')
WINDOWS = ('arched', 'rect', 'round')
STREETS = ('winding', 'grid', 'radial')
MOODS = ('realistic', 'magical', 'dark', 'ancient', 'dramatic', 'colorful')

MOOD_LOOK = {
    'realistic': dict(sky_top='#6fa6df', sky_bottom='#dbe8f2', fog='#c9d6e0', fog_density=0.0016, sun='#fff3dc', sun_intensity=2.4, ambient=0.6, sun_height=0.8),
    'magical': dict(sky_top='#3a2a78', sky_bottom='#e7a6dc', fog='#8f7ad1', fog_density=0.0028, sun='#ffd9fb', sun_intensity=1.8, ambient=0.8, sun_height=0.5),
    'dark': dict(sky_top='#14141c', sky_bottom='#3d3d4b', fog='#2b2b34', fog_density=0.0062, sun='#9aa6c9', sun_intensity=0.9, ambient=0.35, sun_height=0.35),
    'ancient': dict(sky_top='#b88a52', sky_bottom='#f0dfb8', fog='#d9c08f', fog_density=0.0024, sun='#ffe2a8', sun_intensity=2.0, ambient=0.6, sun_height=0.55),
    'dramatic': dict(sky_top='#2c3e60', sky_bottom='#f0a15c', fog='#b98a6a', fog_density=0.0032, sun='#ffb66b', sun_intensity=2.6, ambient=0.45, sun_height=0.3),
    'colorful': dict(sky_top='#4fa9ff', sky_bottom='#ffe0f0', fog='#f6dff0', fog_density=0.0014, sun='#fff6d8', sun_intensity=2.4, ambient=0.75, sun_height=0.8),
}

DEFAULT_SPEC = {
    'terrain': {'kind': 'mountains', 'relief': 0.5, 'sharpness': 0.4},
    'water': {'sea': False, 'lake': False, 'river': False},
    'climate': {'precip': 'none', 'fog': False, 'vegetation': 'temperate', 'snow_roofs': False, 'snow_ground': False},
    'nature': {'trees': 0.35},
    'architecture': {'material': 'stone', 'roof': 'gable', 'window': 'rect', 'wall_color': None, 'roof_color': None, 'trim_color': None, 'ornament': []},
    'urban': {'density': 0.55, 'street': 'winding', 'stairs': False, 'bridges': False, 'plaza': True},
    'mood': 'realistic',
}


def merge(base, extra):
    out = dict(base)
    for key, value in extra.items():
        out[key] = merge(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return out


def read_terrain(toks, spec, notes):
    sharp = has_any(toks, ['חד', 'חדים', 'חדות', 'מחודד', 'מחודדים', 'מחודדות', 'תלול', 'תלולים', 'תלולות', 'שיני', 'sharp', 'jagged', 'steep', 'spiky'])
    tall = has_any(toks, ['גבוה', 'גבוהים', 'גבוהות', 'עצום', 'עצומים', 'עצומות', 'מתנשא', 'מתנשאים', 'high', 'tall', 'huge', 'towering'])
    mountains = has_any(toks, ['הר', 'הרים', 'הרי', 'רכס', 'רכסים', 'פסגה', 'פסגות', 'הררי', 'mountain', 'mountains', 'peaks', 'ridge', 'alpine'])
    cliffs = has_any(toks, ['צוק', 'צוקים', 'מצוק', 'מצוקים', 'cliff', 'cliffs'])
    sea = has_any(toks, ['ים', 'חוף', 'חופים', 'נמל', 'sea', 'coast', 'beach', 'port', 'harbor', 'harbour', 'ocean'])
    kinds = [
        ('sharp_mountains', mountains and (sharp or tall)),
        ('cliff_port', cliffs and sea),
        ('islands', has_any(toks, ['אי', 'איים', 'island', 'islands', 'archipelago'])),
        ('canyon', has_any(toks, ['קניון', 'ערוץ', 'canyon', 'gorge'])),
        ('valley', has_any(toks, ['עמק', 'עמקים', 'valley'])),
        ('mountains', mountains or cliffs),
        ('desert', has_any(toks, ['מדבר', 'מדברי', 'מדברית', 'דיונות', 'desert', 'dunes'])),
        ('coast', sea),
        ('plains', has_any(toks, ['מישור', 'מישורים', 'שדות', 'plain', 'plains', 'meadow', 'fields'])),
    ]
    picked = next((k for k, hit in kinds if hit), None)
    if picked:
        spec['terrain']['kind'] = picked
        notes.append(f'שטח: {picked}')
    spec['terrain']['relief'] = 0.9 if tall else (0.7 if sharp else spec['terrain']['relief'])
    spec['terrain']['sharpness'] = 0.95 if sharp else spec['terrain']['sharpness']
    if picked == 'sharp_mountains':
        spec['terrain']['relief'] = max(spec['terrain']['relief'], 0.8)
        spec['terrain']['sharpness'] = max(spec['terrain']['sharpness'], 0.8)
    spec['water']['sea'] = picked in ('islands', 'coast', 'cliff_port') or (sea and picked != 'sharp_mountains')
    spec['water']['lake'] = has_any(toks, ['אגם', 'אגמים', 'lake', 'lakes'])
    spec['water']['river'] = has_any(toks, ['נהר', 'נהרות', 'נחל', 'נחלים', 'מפל', 'מפלים', 'river', 'rivers', 'stream', 'waterfall', 'waterfalls'])
    spec['water']['falls'] = has_any(toks, ['מפל', 'מפלים', 'waterfall', 'waterfalls'])


def read_climate(toks, spec, notes):
    climate = spec['climate']
    snow = has_any(toks, ['שלג', 'שלגים', 'מושלג', 'מושלגים', 'מושלגות', 'קרח', 'חורף', 'חורפי', 'snow', 'snowy', 'winter', 'frozen'])
    snow_roofs = snow and (has_any(toks, ['גג', 'גגות', 'roof', 'roofs', 'rooftops']) or climate['snow_roofs'])
    rain = has_any(toks, ['גשם', 'גשמים', 'גשום', 'סערה', 'סופה', 'rain', 'rainy', 'storm', 'stormy'])
    tropical = has_any(toks, ['טרופי', 'טרופית', 'טרופיים', 'ג׳ונגל', 'גונגל', 'דקל', 'דקלים', 'עצי-דקל', 'tropical', 'jungle', 'palm', 'palms'])
    desert = has_any(toks, ['מדבר', 'מדברי', 'מדברית', 'חמסין', 'desert', 'arid'])
    fog = has_any(toks, ['ערפל', 'ערפילי', 'ערפיליים', 'אובך', 'fog', 'foggy', 'mist', 'misty'])
    snow_only_roofs = snow_roofs and tropical
    climate['precip'] = 'snow' if snow and not snow_only_roofs and not desert else ('rain' if rain else 'none')
    climate['snow_roofs'] = bool(snow)
    climate['snow_ground'] = bool(snow) and not snow_only_roofs and not tropical
    climate['fog'] = fog
    climate['vegetation'] = 'tropical' if tropical else ('desert' if desert else ('alpine' if snow else climate['vegetation']))
    if spec['terrain']['kind'] == 'desert':
        climate['vegetation'] = 'desert' if not tropical else climate['vegetation']
    notes.append(f"אקלים: משקעים={climate['precip']}, צמחייה={climate['vegetation']}, שלג על גגות={climate['snow_roofs']}")


def read_nature(toks, spec):
    forest = has_any(toks, ['יער', 'יערות', 'עצים', 'עצי', 'forest', 'forests', 'woods', 'trees'])
    bare = has_any(toks, ['חשוף', 'שומם', 'barren', 'bare'])
    spec['nature']['trees'] = 0.85 if forest else (0.05 if bare else spec['nature']['trees'])
    if spec['climate']['vegetation'] == 'desert' and not forest:
        spec['nature']['trees'] = 0.08


def read_architecture(toks, spec, notes):
    arch = spec['architecture']
    materials = [
        ('sandstone', ['אבן-חול', 'sandstone']),
        ('dark_stone', ['אבן-שחורה', 'obsidian', 'אובסידיאן', 'basalt']),
        ('marble', ['שיש', 'marble']),
        ('brick', ['לבנים', 'לבנה', 'brick', 'bricks']),
        ('ice', ['קרח', 'ice', 'crystal', 'גביש']),
        ('wood', ['עץ', 'עצים', 'עץ', 'wood', 'wooden', 'timber']),
        ('stone', ['אבן', 'אבנים', 'stone']),
        ('plaster', ['טיח', 'לבן-טיח', 'plaster', 'stucco']),
    ]
    text_has = lambda stems: has_any(toks, stems)
    joined = ' '.join(toks)
    material = next((m for m, stems in materials if text_has(stems) or any(s in joined for s in stems if '-' in s)), None)
    if 'אבן חול' in joined or 'אבן-חול' in joined:
        material = 'sandstone'
    house_context = has_any(toks, ['בית', 'בתים', 'מבנים', 'בנייה', 'בניה', 'אדריכלות', 'house', 'houses', 'buildings', 'architecture'])
    if material == 'wood' and not house_context and not has_any(toks, ['עץ', 'wood', 'wooden', 'timber']):
        material = None
    arch['material'] = material or arch['material']
    roofs = [
        ('pointed', ['מחודד', 'מחודדים', 'מחודדות', 'חרוטי', 'חרוטיים', 'חד', 'חדים', 'pointed', 'conical', 'spire', 'spires', 'steep']),
        ('dome', ['כיפה', 'כיפות', 'כיפתי', 'כיפתיים', 'dome', 'domes', 'domed', 'onion']),
        ('curved', ['קמור', 'קמורים', 'קמורות', 'מעוגל', 'מעוגלים', 'curved', 'pagoda', 'פגודה']),
        ('flat', ['שטוח', 'שטוחים', 'שטוחות', 'flat']),
    ]
    roof_words = ['גג', 'גגות', 'roof', 'roofs']
    roof_idx = [i for i, t in enumerate(toks) if has_any([t], roof_words)]
    near = lambda i: toks[max(0, i - 1):i + 3]
    roof = next((r for r, stems in roofs if any(has_any(near(i), stems) for i in roof_idx)), None)
    arch['roof'] = roof or arch['roof']
    win_idx = [i for i, t in enumerate(toks) if has_any([t], ['חלון', 'חלונות', 'window', 'windows'])]
    window_kinds = [
        ('arched', ['קמור', 'קמורים', 'קמורות', 'קשת', 'קשתות', 'קשתי', 'קשתיים', 'arched', 'arch', 'arches', 'gothic', 'גותי', 'גותיים']),
        ('round', ['עגול', 'עגולים', 'עגולות', 'round', 'circular']),
        ('rect', ['מרובע', 'מרובעים', 'מרובעות', 'ישר', 'ישרים', 'square', 'rectangular']),
    ]
    window = next((w for w, stems in window_kinds if any(has_any(toks[max(0, i - 1):i + 3], stems) for i in win_idx)), None)
    arch['window'] = window or arch['window']
    arch['wall_color'] = color_near(toks, ['קיר', 'קירות', 'בית', 'בתים', 'מבנה', 'מבנים', 'wall', 'walls', 'houses', 'house']) or arch['wall_color']
    arch['roof_color'] = color_near(toks, roof_words) or arch['roof_color']
    arch['trim_color'] = color_near(toks, ['קישוט', 'קישוטים', 'מסגרת', 'מסגרות', 'trim', 'trims']) or arch['trim_color']
    ornaments = [
        ('gold', ['זהב', 'זהוב', 'זהובים', 'gold', 'golden', 'gilded']),
        ('carvings', ['גילופים', 'מגולף', 'מגולפים', 'carved', 'carvings']),
        ('banners', ['דגלים', 'באנרים', 'banners', 'flags']),
        ('balconies', ['מרפסת', 'מרפסות', 'balcony', 'balconies']),
    ]
    arch['ornament'] = [o for o, stems in ornaments if has_any(toks, stems)]
    notes.append(f"אדריכלות: חומר={arch['material']}, גג={arch['roof']}, חלונות={arch['window']}")


def read_urban(toks, spec, notes):
    urban = spec['urban']
    dense = has_any(toks, ['צפוף', 'צפופה', 'צפופים', 'צפופות', 'דחוס', 'דחוסים', 'dense', 'crowded', 'packed'])
    sparse = has_any(toks, ['מרווח', 'מרווחים', 'פרברים', 'כפר', 'כפרי', 'קטן', 'sparse', 'village', 'suburbs', 'rural', 'scattered'])
    urban['density'] = 0.9 if dense else (0.3 if sparse else urban['density'])
    street_kinds = [
        ('grid', ['רשת', 'גריד', 'מרובעת', 'מאונכים', 'grid', 'orthogonal']),
        ('radial', ['רדיאלי', 'מעגלי', 'מעגלים', 'radial', 'concentric', 'ring']),
        ('winding', ['מפותל', 'מפותלים', 'מפותלות', 'מתפתל', 'מתפתלים', 'מתפתלות', 'שביל', 'שבילים', 'סמטאות', 'סמטה', 'winding', 'twisting', 'alleys', 'paths', 'trails']),
    ]
    urban['street'] = next((s for s, stems in street_kinds if has_any(toks, stems)), urban['street'])
    urban['stairs'] = has_any(toks, ['מדרגות', 'מדרגה', 'מדרגות-אבן', 'stairs', 'staircase', 'steps', 'stairways'])
    urban['bridges'] = has_any(toks, ['גשר', 'גשרים', 'bridge', 'bridges'])
    urban['plaza'] = True
    if spec['terrain']['kind'] in ('sharp_mountains', 'cliff_port', 'canyon'):
        urban['stairs'] = True
    notes.append(f"תכנון עירוני: צפיפות={urban['density']}, רחובות={urban['street']}, מדרגות={urban['stairs']}, גשרים={urban['bridges']}")


def read_mood(toks, spec):
    moods = [
        ('dark', ['אפל', 'אפלה', 'אפלים', 'קודר', 'קודרת', 'מאיים', 'dark', 'gloomy', 'grim', 'sinister']),
        ('magical', ['קסום', 'קסומה', 'קסומים', 'קסם', 'מיסטי', 'מיסטית', 'magical', 'magic', 'mystic', 'enchanted']),
        ('dramatic', ['דרמטי', 'דרמטית', 'דרמטיים', 'dramatic', 'epic']),
        ('ancient', ['עתיק', 'עתיקה', 'עתיקים', 'עתיקות', 'קדום', 'קדומה', 'ancient', 'old', 'medieval', 'ימי-ביניימי']),
        ('colorful', ['צבעוני', 'צבעונית', 'צבעוניים', 'צבעוניות', 'colorful', 'colourful', 'vibrant']),
        ('realistic', ['מציאותי', 'מציאותית', 'ריאליסטי', 'realistic']),
    ]
    spec['mood'] = next((m for m, stems in moods if has_any(toks, stems)), spec['mood'])


def interpret_world_rules(text):
    toks = tokens(text)
    spec = json.loads(json.dumps(DEFAULT_SPEC))
    notes = []
    read_terrain(toks, spec, notes)
    read_climate(toks, spec, notes)
    read_nature(toks, spec)
    read_architecture(toks, spec, notes)
    read_urban(toks, spec, notes)
    read_mood(toks, spec)
    spec['seed'] = zlib.crc32(text.encode('utf-8')) & 0x7FFFFFFF
    spec['notes'] = notes
    spec['source'] = 'rules'
    return spec


def ollama_json(prompt, timeout=75):
    body = json.dumps({'model': OLLAMA_MODEL, 'prompt': prompt, 'stream': False, 'format': 'json', 'keep_alive': '10m',
                       'options': {'temperature': 0.2, 'num_predict': 900}}).encode()
    req = urllib.request.Request(f'{OLLAMA_URL}/api/generate', data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(json.loads(resp.read())['response'])


WORLD_PROMPT = """You convert a fantasy world description (Hebrew or English) into JSON for a procedural world generator.
Return ONLY JSON with exactly these keys and only these allowed values:
{"terrain_kind": one of %s,
 "relief": number 0..1 (height of mountains), "sharpness": number 0..1,
 "sea": bool, "lake": bool, "river": bool,
 "precip": one of %s, "fog": bool, "snow_roofs": bool, "snow_ground": bool,
 "vegetation": one of %s, "trees": number 0..1,
 "material": one of %s, "roof": one of %s, "window": one of %s,
 "wall_color": hex string or null, "roof_color": hex string or null,
 "density": number 0..1, "street": one of %s, "stairs": bool, "bridges": bool,
 "mood": one of %s}
Mixed fantasy is allowed (e.g. palm trees with snow on roofs: vegetation "tropical", precip "none", snow_roofs true).
Description: %s"""


def pick(value, allowed, fallback):
    return value if value in allowed else fallback


def num(value, fallback):
    return max(0.0, min(1.0, float(value))) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def hexcolor(value, fallback):
    ok = isinstance(value, str) and len(value) == 7 and value.startswith('#') and all(c in '0123456789abcdefABCDEF' for c in value[1:])
    return value if ok else fallback


def apply_llm(spec, data):
    t, w, c, n, a, u = spec['terrain'], spec['water'], spec['climate'], spec['nature'], spec['architecture'], spec['urban']
    t['kind'] = pick(data.get('terrain_kind'), TERRAIN_KINDS, t['kind'])
    t['relief'] = num(data.get('relief'), t['relief'])
    t['sharpness'] = num(data.get('sharpness'), t['sharpness'])
    w['sea'] = bool(data.get('sea', w['sea']))
    w['lake'] = bool(data.get('lake', w['lake']))
    w['river'] = bool(data.get('river', w['river']))
    c['precip'] = pick(data.get('precip'), PRECIP, c['precip'])
    c['fog'] = bool(data.get('fog', c['fog']))
    c['snow_roofs'] = bool(data.get('snow_roofs', c['snow_roofs']))
    c['snow_ground'] = bool(data.get('snow_ground', c['snow_ground']))
    c['vegetation'] = pick(data.get('vegetation'), VEGETATION, c['vegetation'])
    n['trees'] = num(data.get('trees'), n['trees'])
    a['material'] = pick(data.get('material'), MATERIALS, a['material'])
    a['roof'] = pick(data.get('roof'), ROOFS, a['roof'])
    a['window'] = pick(data.get('window'), WINDOWS, a['window'])
    a['wall_color'] = hexcolor(data.get('wall_color'), a['wall_color'])
    a['roof_color'] = hexcolor(data.get('roof_color'), a['roof_color'])
    u['density'] = num(data.get('density'), u['density'])
    u['street'] = pick(data.get('street'), STREETS, u['street'])
    u['stairs'] = bool(data.get('stairs', u['stairs']))
    u['bridges'] = bool(data.get('bridges', u['bridges']))
    spec['mood'] = pick(data.get('mood'), MOODS, spec['mood'])
    if t['kind'] in ('sharp_mountains', 'cliff_port', 'canyon'):
        u['stairs'] = True
    return spec


def interpret_world(text, use_llm=True):
    spec = interpret_world_rules(text)
    if use_llm:
        prompt = WORLD_PROMPT % (list(TERRAIN_KINDS), list(PRECIP), list(VEGETATION), list(MATERIALS), list(ROOFS), list(WINDOWS), list(STREETS), list(MOODS), text)
        try:
            data = ollama_json(prompt)
            rules_kind = spec['terrain']['kind']
            spec = apply_llm(spec, data)
            spec['source'] = f'llm:{OLLAMA_MODEL}+rules'
            spec['notes'].append(f'פירוש ע״י מודל מקומי {OLLAMA_MODEL} (שטח לפי חוקים: {rules_kind})')
        except Exception as exc:
            spec['notes'].append(f'המודל המקומי לא זמין ({type(exc).__name__}) — שימוש בחוקים בלבד')
    return spec


ITEM_LEXICON = [
    ('long_table', ['שולחן-ארוך', 'long-table'], 'שולחן עץ ארוך'),
    ('table', ['שולחן', 'שולחנות', 'table', 'tables', 'desk'], 'שולחן'),
    ('chair', ['כיסא', 'כיסאות', 'כסא', 'כסאות', 'chair', 'chairs', 'stools'], 'כיסאות'),
    ('chandelier', ['נברשת', 'נברשות', 'chandelier', 'chandeliers'], 'נברשת'),
    ('curtains', ['וילון', 'וילונות', 'curtain', 'curtains', 'drapes'], 'וילונות'),
    ('rug', ['שטיח', 'שטיחים', 'rug', 'rugs', 'carpet'], 'שטיח'),
    ('throne', ['כס', 'כסא-מלכות', 'כס-מלכות', 'throne'], 'כס מלכות'),
    ('bookshelf', ['ספרייה', 'ספריה', 'ארון-ספרים', 'מדף-ספרים', 'bookshelf', 'bookcase', 'library'], 'ספרייה'),
    ('bed', ['מיטה', 'מיטות', 'bed', 'beds'], 'מיטה'),
    ('column', ['עמוד', 'עמודים', 'column', 'columns', 'pillar', 'pillars'], 'עמודים'),
    ('fireplace', ['אח', 'קמין', 'fireplace', 'hearth'], 'אח'),
    ('banner', ['דגל', 'דגלים', 'באנר', 'באנרים', 'banner', 'banners', 'tapestry', 'tapestries', 'שטיח-קיר'], 'דגלים'),
    ('candelabra', ['פמוט', 'פמוטים', 'candelabra', 'candlestick', 'candles'], 'פמוטים'),
    ('plant', ['עציץ', 'עציצים', 'צמח', 'צמחים', 'plant', 'plants'], 'עציצים'),
    ('statue', ['פסל', 'פסלים', 'statue', 'statues'], 'פסלים'),
]

FLOOR_KINDS = [
    ('marble', ['שיש', 'marble']),
    ('wood', ['פרקט', 'עץ', 'parquet', 'wood', 'wooden']),
    ('stone', ['אבן', 'stone', 'cobble']),
    ('tile', ['אריחים', 'אריח', 'tiles', 'tile', 'mosaic', 'פסיפס']),
    ('checker', ['שחמט', 'משבצות', 'checkerboard', 'checker']),
]

FLOOR_HE = {'marble': 'שיש', 'wood': 'פרקט עץ', 'stone': 'אבן', 'tile': 'אריחים', 'checker': 'שחמט'}
WALL_HE = {'stone': 'אבן', 'plaster': 'טיח', 'wood': 'עץ', 'marble': 'שיש', 'brick': 'לבנים'}
FLOOR_COLORS = {'marble': '#e8e4da', 'wood': '#8a5a32', 'stone': '#7d7a74', 'tile': '#b79a6e', 'checker': '#d9d4c8'}
WALL_MATERIALS = {'stone': '#8d8a82', 'plaster': '#e3d9c3', 'wood': '#7d5a38', 'marble': '#e6e2d8', 'brick': '#a2553b'}


def has_room_word(toks, words):
    return [i for i, t in enumerate(toks) if has_any([t], words)]


def read_items(toks, room):
    comps = []
    for kind, stems, label in ITEM_LEXICON:
        if kind == 'long_table':
            continue
        idx = has_room_word(toks, stems)
        if not idx:
            continue
        i = idx[0]
        count = count_before(toks, i, default=1)
        color = color_near(toks, stems) if kind != 'table' else color_near(toks, stems)
        material = next((m for m, ms in (('wood', ['עץ', 'wood', 'wooden']), ('marble', ['שיש', 'marble']), ('stone', ['אבן', 'stone'])) if has_any(toks[max(0, i - 1):i + 2], ms)), None)
        long_table = has_any(toks[i:i + 4], ['ארוך', 'ארוכה', 'long']) if kind == 'table' else False
        if kind == 'table' and long_table:
            kind, label = 'long_table', 'שולחן עץ ארוך'
        if kind in ('chandelier', 'column', 'banner', 'candelabra', 'statue') and count == 1:
            count = {'chandelier': 2, 'column': 6, 'banner': 4, 'candelabra': 4, 'statue': 2}[kind] if has_any(toks, ['כמה', 'several', 'many']) else count
        if kind == 'chair' and count == 1:
            count = 4
        if kind == 'curtains' and count == 1:
            count = 0
        comps.append({'key': f'item:{kind}', 'label': f'{label}' + (f' ×{count}' if count > 1 else ''), 'type': 'item', 'action': 'add',
                      'kind': kind, 'count': count, 'color': color, 'material': material})
    removes = has_any(toks, ['הסר', 'הסירו', 'תסיר', 'תוריד', 'הוצא', 'remove', 'delete', 'without', 'בלי'])
    if removes:
        for comp in comps:
            comp['action'] = 'remove'
            comp['label'] = comp['label'] + ' (הסרה)'
    return comps


def read_surfaces(toks, room):
    comps = []
    floor_idx = has_room_word(toks, ['רצפה', 'רצפת', 'floor', 'flooring'])
    if floor_idx:
        window = toks[max(0, floor_idx[0] - 1):floor_idx[0] + 4]
        kind = next((k for k, stems in FLOOR_KINDS if has_any(window, stems)), None)
        color = color_near(toks, ['רצפה', 'רצפת', 'floor'], 3)
        if kind or color:
            kind = kind or room['floor']['material']
            comps.append({'key': 'floor', 'label': 'רצפת ' + FLOOR_HE[kind], 'type': 'floor', 'action': 'set', 'material': kind, 'color': color or FLOOR_COLORS[kind]})
    wall_idx = has_room_word(toks, ['קיר', 'קירות', 'wall', 'walls'])
    if wall_idx:
        window = toks[max(0, wall_idx[0] - 1):wall_idx[0] + 4]
        material = next((m for m, stems in (('wood', ['עץ', 'wood', 'wooden', 'פנלים']), ('marble', ['שיש', 'marble']), ('brick', ['לבנים', 'brick']), ('stone', ['אבן', 'stone']), ('plaster', ['טיח', 'plaster'])) if has_any(window, stems)), None)
        color = color_near(toks, ['קיר', 'קירות', 'wall', 'walls'], 3)
        if material or color:
            material = material or room['walls']['material']
            comps.append({'key': 'walls', 'label': 'קירות' + (' ' + WALL_HE[material] if material else ''), 'type': 'walls', 'action': 'set', 'material': material, 'color': color or WALL_MATERIALS.get(material, room['walls']['color'])})
    ceil_idx = has_room_word(toks, ['תקרה', 'קמרון', 'קורות', 'ceiling', 'vault', 'vaulted', 'beams'])
    if ceil_idx:
        style = 'vaulted' if has_any(toks, ['קמרון', 'קמורה', 'vault', 'vaulted']) else ('beams' if has_any(toks, ['קורות', 'beams']) else 'flat')
        comps.append({'key': 'ceiling', 'label': f'תקרה: {style}', 'type': 'ceiling', 'action': 'set', 'style': style, 'color': color_near(toks, ['תקרה', 'ceiling'])})
    return comps


def read_windows(toks, room):
    win_idx = has_room_word(toks, ['חלון', 'חלונות', 'window', 'windows'])
    comps = []
    if win_idx:
        i = win_idx[0]
        window = toks[max(0, i - 2):i + 4]
        style = next((s for s, stems in (('arched', ['קמור', 'קמורים', 'קמורות', 'קשת', 'קשתות', 'קשתי', 'arched', 'gothic', 'גותיים']), ('round', ['עגול', 'עגולים', 'round']), ('rect', ['מרובע', 'מרובעים', 'ישר', 'square'])) if has_any(window, stems)), None)
        large = has_any(window, ['גדול', 'גדולים', 'גדולות', 'ענק', 'ענקיים', 'רחב', 'רחבים', 'large', 'big', 'huge', 'tall'])
        small = has_any(window, ['קטן', 'קטנים', 'קטנות', 'small'])
        count = count_before(toks, i, default=0)
        color = color_near(toks, ['חלון', 'חלונות', 'window', 'windows'])
        stained = has_any(toks, ['ויטראז', 'ויטראז׳', 'צבעוני', 'stained', 'vitraj'])
        if style or large or small or count or color or stained:
            comps.append({'key': 'windows', 'label': 'חלונות' + (' גדולים' if large else (' קטנים' if small else '')) + (f' ({style})' if style else ''), 'type': 'windows', 'action': 'set',
                          'style': style, 'size': 'large' if large else ('small' if small else None), 'count': count or None, 'color': color, 'stained': stained or None})
    return comps


def read_light(toks, room):
    if has_any(toks, ['חמימה', 'חמים', 'נרות', 'warm', 'candlelight', 'cozy']):
        return [{'key': 'light', 'label': 'תאורה חמימה', 'type': 'light', 'action': 'set', 'tone': 'warm', 'intensity': 1.2}]
    if has_any(toks, ['קרה', 'קרים', 'כחלחלה', 'cool', 'cold', 'moonlight']):
        return [{'key': 'light', 'label': 'תאורה קרה', 'type': 'light', 'action': 'set', 'tone': 'cool', 'intensity': 1.0}]
    if has_any(toks, ['בהירה', 'בהירים', 'bright', 'brighter']):
        return [{'key': 'light', 'label': 'תאורה בהירה', 'type': 'light', 'action': 'set', 'tone': 'neutral', 'intensity': 1.6}]
    return []


def interpret_room_rules(text, room):
    toks = tokens(text)
    return read_items(toks, room) + read_surfaces(toks, room) + read_windows(toks, room) + read_light(toks, room)


ROOM_PROMPT = """You convert a Hebrew or English room-design request into JSON for a 3D room editor.
Return ONLY JSON: {"components":[ ... ]} where each component is one of:
{"type":"item","action":"add"|"remove","kind":one of %s,"count":int 1..12,"color":hex or null,"material":"wood"|"marble"|"stone"|null}
{"type":"floor","material":one of ["marble","wood","stone","tile","checker"],"color":hex or null}
{"type":"walls","material":one of ["stone","plaster","wood","marble","brick"],"color":hex or null}
{"type":"windows","style":"arched"|"rect"|"round"|null,"size":"large"|"small"|null,"count":int or null,"color":hex or null}
{"type":"ceiling","style":"flat"|"vaulted"|"beams"}
{"type":"light","tone":"warm"|"cool"|"neutral","intensity":0.6..1.8}
Only include things the user asked for or that clearly fit a style they described (e.g. "royal" suggests chandeliers, a rug, curtains, columns).
Request: %s"""

ITEM_KINDS = [k for k, _, _ in ITEM_LEXICON]
LABELS = {k: label for k, _, label in ITEM_LEXICON}


def components_from_llm(data, room):
    out = []
    for raw in (data.get('components') or [])[:14]:
        kind_type = raw.get('type')
        if kind_type == 'item' and raw.get('kind') in ITEM_KINDS:
            count = int(max(1, min(12, raw.get('count') or 1)))
            label = LABELS[raw['kind']] + (f' ×{count}' if count > 1 else '')
            action = 'remove' if raw.get('action') == 'remove' else 'add'
            out.append({'key': f"item:{raw['kind']}", 'label': label + (' (הסרה)' if action == 'remove' else ''), 'type': 'item', 'action': action, 'kind': raw['kind'],
                        'count': count, 'color': hexcolor(raw.get('color'), None), 'material': raw.get('material')})
        elif kind_type == 'floor' and raw.get('material') in FLOOR_COLORS:
            out.append({'key': 'floor', 'label': 'רצפת ' + FLOOR_HE[raw['material']], 'type': 'floor', 'action': 'set', 'material': raw['material'], 'color': hexcolor(raw.get('color'), FLOOR_COLORS[raw['material']])})
        elif kind_type == 'walls' and raw.get('material') in WALL_MATERIALS:
            out.append({'key': 'walls', 'label': 'קירות ' + WALL_HE[raw['material']], 'type': 'walls', 'action': 'set', 'material': raw['material'], 'color': hexcolor(raw.get('color'), WALL_MATERIALS[raw['material']])})
        elif kind_type == 'windows':
            out.append({'key': 'windows', 'label': 'חלונות', 'type': 'windows', 'action': 'set', 'style': pick(raw.get('style'), WINDOWS, None), 'size': pick(raw.get('size'), ('large', 'small'), None),
                        'count': int(raw['count']) if isinstance(raw.get('count'), (int, float)) else None, 'color': hexcolor(raw.get('color'), None), 'stained': None})
        elif kind_type == 'ceiling' and raw.get('style') in ('flat', 'vaulted', 'beams'):
            out.append({'key': 'ceiling', 'label': f"תקרה: {raw['style']}", 'type': 'ceiling', 'action': 'set', 'style': raw['style'], 'color': None})
        elif kind_type == 'light' and raw.get('tone') in ('warm', 'cool', 'neutral'):
            out.append({'key': 'light', 'label': f"תאורה {raw['tone']}", 'type': 'light', 'action': 'set', 'tone': raw['tone'], 'intensity': max(0.6, min(1.8, float(raw.get('intensity') or 1.0)))})
    return out


def interpret_room(text, room, use_llm=True, context=''):
    rules = interpret_room_rules(text, room)
    source = 'rules'
    comps = rules
    notes = []
    if use_llm:
        try:
            from .models import ask_json
            data, model_name = ask_json('Return only JSON.', ROOM_PROMPT % (ITEM_KINDS, text + context), ())
            llm = components_from_llm(data, room)
            seen = {c['key'] for c in rules}
            extra = [c for c in llm if c['key'] not in seen]
            comps = rules + extra
            long_table = any(c['key'] == 'item:long_table' for c in comps)
            comps = [c for c in comps if not (long_table and c['key'] == 'item:table')]
            source = f'{model_name}+rules'
        except Exception as exc:
            notes.append(f'המודל המקומי לא זמין ({type(exc).__name__}) — שימוש בחוקים בלבד')
    return comps, source, notes
