import copy

from . import designer
from .basemap import is_rome, place_names, rome_plan_defaults
from .builder import build_scene, survey_map
from .cartography import free_spot, height_at
from .city import PALACE_ROOMS, default_room_design
from .deliver_link import DELIVERS, DeliverLink, context_text, period_of, public
from .foundry_link import Foundry, dress
from .rag import Rag
from .historical import DOMUS_FLAVIA_DESIGNS, DOMUS_FLAVIA_ROOMS, DOMUS_FLAVIA_SOURCES
from .houses import house_design, house_rooms
from .objects import build_model, plan_object
from .interpreter import interpret_world_rules
from .life import LIFE_VERSION, climate_plan, plan_life
from .population import DYES, SKINS, build_population, design_costumes
from .plan import create_plan, describe_changes, edit_plan, normalize, rules_plan, summarize
from .store import Store


def legacy_spec(plan):
    s = plan['style']
    return {'architecture': {'material': s['material'], 'window': s['window'], 'wall_color': s['wall_colors'][0] if s['wall_colors'] else None}}


def with_rome_defaults(plan, source, has_image=False, explicit=frozenset(), weather=False):
    if not is_rome(plan):
        return plan
    names = place_names(plan)
    base = normalize(rome_plan_defaults(plan['basemap']), names)
    if '+rules' not in source:
        return {**base, 'seed': plan['seed']}
    out = copy.deepcopy(plan)
    out['terrain'] = base['terrain']
    out['water'] = {**out['water'], 'rivers': [], 'sea_side': 'none'}
    out['landmarks'] = [m for m in out['landmarks'] if m['at'] in names]
    out['palace'] = {**base['palace'], **({'at': out['palace']['at']} if out['palace']['at'] in names else {})}
    out['nature']['species'] = out['nature']['species'] or base['nature']['species']
    out['city']['size'] = 'large'
    out['style']['towers'] = min(out['style']['towers'], 0.05)
    out['style']['timber'] = out['style']['timber'] and 'style.timber' in explicit
    out['style']['chimneys'] = False
    out['city']['walls'] = out['city']['walls'] and 'city.walls' in explicit
    out['climate'] = out['climate'] if weather else base['climate']
    out['condition'] = base['condition'] if plan['basemap'] == 'rome_315' and 'condition' not in explicit else out['condition']
    for key in ('condition', 'time_of_day'):
        if key in explicit:
            continue
        out[key] = base[key] if key == 'time_of_day' and out[key] == 'day' else out[key]
    if not has_image:
        out['style']['wall_colors'] = base['style']['wall_colors']
        out['style']['roof_colors'] = base['style']['roof_colors']
        for key in ('material', 'roof', 'roof_pitch', 'window', 'floors', 'arcades', 'balconies', 'shutters'):
            out['style'][key] = base['style'][key]
    out['style']['wall_colors'] = out['style']['wall_colors'] or base['style']['wall_colors']
    out['style']['roof_colors'] = out['style']['roof_colors'] or base['style']['roof_colors']
    return out


RECONSTRUCT_WORDS = ('כפי שהיה', 'כמו שהיה', 'שחזר', 'שחזור', 'היסטורי', 'באמת', 'reconstruct', 'as it was', 'historical')


def historical_design(room, spec):
    data = DOMUS_FLAVIA_DESIGNS[room['id']]
    base = default_room_design(room, spec)
    base.update({k: copy.deepcopy(data[k]) for k in ('floor', 'walls', 'ceiling', 'windows', 'light')})
    base['door_north'] = any(d_['wall'] == 'n' for d_ in room['doors']) or bool(room.get('apse'))
    comps = [{'type': 'item', 'action': 'add', 'kind': it['kind'], 'count': it.get('count', 1), 'color': it.get('color'), 'material': None, 'h': it.get('h')} for it in data['items']]
    return designer.apply_components(base, comps)


class Service:
    def __init__(self, store=None, link=None, foundry=None):
        self.store = store or Store()
        self.foundry = foundry or Foundry('auto')
        self.rag = Rag(self.store)
        self.rag.seed_all()
        self.link = link or DeliverLink('auto')
        self.link.store = self.store
        self.link.rag = self.rag

    def build_plan(self, description, images, palette, use_llm, basemap=None, context=''):
        hint = {'rome_476': '\n(Project map: historical Rome c. 476, basemap "rome_476")', 'rome_315': '\n(Project map: Rome in its glory c. 315, basemap "rome_315")'}.get(basemap, '')
        guess, explicit = rules_plan(description)
        spec = interpret_world_rules(description)
        weather = spec['climate']['precip'] != 'none' or spec['climate']['fog'] or spec['climate']['snow_roofs']
        names = place_names({'basemap': basemap or guess['basemap']})
        plan, source, notes = create_plan(description + hint, images, palette, use_llm, names, context)
        plan['basemap'] = basemap or (guess['basemap'] if 'basemap' in explicit else 'none')
        if not weather and not images:
            plan['climate'] = {**plan['climate'], 'precip': 'none', 'fog': False, 'snow_roofs': False, 'snow_ground': False}
        return with_rome_defaults(plan, source, bool(images), explicit, weather), source, notes

    def create_world(self, name, description, use_llm=True, image=None, palette=(), basemap=None):
        images = [image] if image else []
        basemap = basemap if is_rome(basemap or '') else None
        guess_spec = {'basemap': basemap or rules_plan(description)[0]['basemap']}
        result = self.link.run('fantasy.world_planner', lambda ctx: self.build_plan(description, images, palette, use_llm, basemap, context_text(ctx)), {'description': description, 'image': bool(image)},
                               world_spec=guess_spec, query=description)
        planner_ctx = self.link.last
        plan, source, notes = result
        scene = self.map_then_build(plan)
        designs = {r['id']: default_room_design(r, legacy_spec(plan)) for r in PALACE_ROOMS}
        designs['chamber']['door_north'] = False
        image_name = self.store.save_image(image) if image else None
        wid = self.store.create_world(name or plan['title'] or 'עולם חדש', description, {**plan, 'source': source, 'notes': notes, 'image': image_name, 'deliver': public(planner_ctx)}, scene, designs)
        self.store.save_world_version(wid, {**plan, 'source': source, 'notes': notes, 'image': image_name}, scene, 'גרסה ראשונה: ' + (description[:80]))
        asset = self.to_library('world_plan', f"תוכנית עולם: {name or plan['title'] or description[:40]}", {'plan': plan}, wid)
        self.index_built(wid, 'world_plan', f"תוכנית עולם: {name or description[:40]}", f"תיאור: {description[:300]}. " + ' '.join(summarize(plan)), 'world', 'fantasy.world_planner', asset)
        self.build_life(wid)
        return wid

    def map_then_build(self, plan):
        query = 'Roman city plan: streets and paving, insulae and domus density, markets and shops, monuments'
        site = self.link.run('fantasy.cartographer', lambda ctx: survey_map(plan), {'plan': plan.get('title'), 'basemap': plan.get('basemap')}, world_spec=plan, query=query)
        return self.link.run('fantasy.world_generator', lambda: build_scene(site), {'map': site['report']})

    def set_clock(self, wid, hour=None, month=None, day=None, weather=None):
        world = self.store.world(wid)
        if world is None:
            return None
        life = world['scene'].get('life') or {}
        if not life.get('climate'):
            self.build_life(wid)
            world = self.store.world(wid)
            life = world['scene'].get('life') or {}
        if not life.get('climate'):
            return None
        c = life['climate']
        hour is not None and c.update({'start_hour': float(hour) % 24})
        month is not None and c.update({'start_month': int(month) % 12})
        day is not None and c.update({'start_day': max(1, min(c.get('days_in_month', [31] * 12)[c['start_month']], int(day)))})
        weather in ('clear', 'cloudy', 'rain', 'storm', 'fog', 'snow') and c.update({'start_weather': weather})
        self.store.save_scene(wid, world['scene'])
        return {k: c.get(k) for k in ('start_hour', 'start_month', 'start_day', 'start_weather')}

    def ensure_population(self, wid=None, use_llm=False):
        era = 'rome_imperial'
        out_dir = self.store.path.parent / 'models' / 'population' / era
        query = 'Roman clothing by class: toga with purple stripe, tunic colours and dyes, stola and palla, cloaks for rain, soldiers, vigiles, children, vestals, litter bearers'
        costumes, notes = self.link.run('fantasy.costume_designer', lambda ctx: design_costumes(context_text(ctx), use_llm), {'era': era, 'use_llm': use_llm},
                                        world_spec={'basemap': 'rome_315'}, query=query)
        costume_ctx = self.link.last
        tools = ['blender'] + (['world3d.library', 'world3d.assets', 'gltfpack'] if self.foundry.enabled else [])
        result = self.link.run('fantasy.character_builder', lambda: dress(build_population(costumes, out_dir), costumes, self.foundry, out_dir, DYES, SKINS),
                               {'types': [c['name'] for c in costumes]}, tools=tools)
        result = {**result, 'era': era, 'notes': notes, 'deliver': public(costume_ctx)}
        stored = {(a['params'].get('model'), a['params'].get('costume')) for a in self.store.assets('character')}
        for t in result['types'] if result.get('ok') else []:
            model = f"/models/population/{era}/{t['file']}"
            key = (model, t['name'] if t.get('body') else None)
            if key in stored:
                continue
            body = t.get('body')
            params = {'model': model, 'role': t['role'], 'animations': t['animations'], 'tags': t['tags'], **({'costume': t['name'], 'tint': t['tint'], 'body': body} if body else {})}
            asset = self.to_library('character', f"דמות{' ריאליסטית' if body else ''}: {t['label']}", params, wid)
            text = (f"דמות ריאליסטית: גוף MPFB ({body['variant']}) מספריית World Foundry, עור MakeHuman CC0, לבוש בצבעי התלבושת {t['tint']}. " if body else 'דמות מונפשת פרוצדורלית. ') + \
                   f"אנימציות: {', '.join(t['animations'])}. תפקיד: {t['role']}. תגיות: {', '.join(t['tags'])}. אפשר לשימוש חוזר בכל עולם עם תלבושת דומה."
            self.index_built(wid, 'character', f"דמות: {t['label']}", text, f"character:{t['name']}", 'fantasy.character_builder', asset)
        return result

    def build_life(self, wid, use_llm=False):
        world = self.store.world(wid)
        plan = world['spec'] if world else {}
        if not world or not is_rome(plan):
            return None
        population = self.ensure_population(wid, use_llm)
        climate = self.link.run('fantasy.climate_master', lambda ctx: climate_plan(None, plan.get('time_of_day', 'day')), {'era': plan['basemap']}, world_spec=plan,
                                query='climate of Rome by season: rain, storms, snow, fog over the Tiber')
        climate_ctx = self.link.last
        scene = world['scene']
        life = self.link.run('fantasy.life_director', lambda ctx: plan_life(scene, plan, population, context_text(ctx)), {'era': plan['basemap'], 'world': wid}, world_spec=plan,
                             query='daily life in Rome: markets and shops, carts at night under the Lex Julia, litters and bearers, boats on the Tiber, the night watch, the hours of the day')
        life_ctx = self.link.last
        if not life:
            scene['life'] = {'version': LIFE_VERSION, 'off': True, 'reason': population.get('error') or 'אין חיים לעולם הזה'}
            self.store.save_scene(wid, scene)
            return scene['life']
        life['climate'] = climate
        life['delivers'] = [population['deliver'], public(climate_ctx), public(life_ctx), {'deliver': 'fantasy.character_builder', 'title': DELIVERS['fantasy.character_builder']['title'],
                                                                                         'model': 'Blender 5.3', 'facts': [], 'related': [], 'cached': population.get('cached'),
                                                                                         'tools': population.get('foundry', {}) and population['foundry']['tools'], 'realistic': population.get('realistic', 0)}]
        life['costume_notes'] = population['notes']
        scene['life'] = life
        self.store.save_scene(wid, scene)
        summary = {'agents': life['agents'], 'types': len(life['population']['types']), 'markets': len(life['markets']), 'carts_night': life['carts']['night'], 'boats': life['boats']['count']}
        asset = self.to_library('life_plan', f"תוכנית חיים: {world['name']}", summary, wid)
        self.index_built(wid, 'life_plan', f"תוכנית חיים: {world['name']}",
                         f"{life['label']}. {summary['agents']} אנשים, {summary['types']} סוגי דמויות, {summary['markets']} שווקים, עד {summary['carts_night']} עגלות בלילה, {summary['boats']} סירות. {life['carts']['rule']}.",
                         'world_life', 'fantasy.life_director', asset)
        return life

    def world_payload(self, wid):
        world = self.store.world(wid)
        if world is None:
            return None
        if is_rome(world['spec']) and (world['scene'].get('life') or {}).get('version') != LIFE_VERSION:
            self.build_life(wid)
            world = self.store.world(wid)
        rooms = self.store.rooms_latest(wid)
        plan = world['spec']
        return {'world': world, 'rooms': {rid: r['design'] for rid, r in rooms.items()}, 'versions': {rid: r['version'] for rid, r in rooms.items()},
                'player': self.store.player(wid), 'assets': self.store.assets(), 'plan_summary': summarize(plan) if 'style' in plan and 'districts' in plan else [],
                'world_versions': self.store.world_versions(wid),
                'objects': [{**o, 'model': f"/models/{wid}/{o['model']}" if o['model'] else None} for o in self.store.objects(wid)]}

    def propose_plan(self, wid, text, image=None, use_llm=True):
        world = self.store.world(wid)
        current = world['spec']
        if 'districts' not in current:
            return None
        clean = {k: v for k, v in current.items() if k not in ('source', 'notes', 'image')}
        names = place_names(clean)
        plan, source, notes = self.link.run('fantasy.world_planner', lambda ctx: edit_plan(clean, text, [image] if image else [], use_llm, names, context_text(ctx)), {'edit': text},
                                            world_spec=clean, query=text, object_id='world', kind='world_plan')
        planner_ctx = self.link.last
        scene = self.map_then_build(plan)
        changes = describe_changes({k: v for k, v in clean.items() if k != 'seed'}, {k: v for k, v in plan.items() if k != 'seed'})
        pid = self.store.add_plan_proposal(wid, text, source, plan, scene, changes)
        return {'id': pid, 'changes': changes, 'source': source, 'notes': notes, 'summary': summarize(plan), 'scene': scene, 'current_scene': world['scene'], 'deliver': public(planner_ctx)}

    def resolve_plan(self, pid, action):
        prop = self.store.plan_proposal(pid)
        if prop is None or prop['status'] != 'PENDING':
            return None
        if action != 'apply':
            self.store.resolve_plan_proposal(pid, 'REJECTED')
            return {'status': 'REJECTED'}
        version = self.store.save_world_version(prop['world_id'], {**prop['plan'], 'source': prop['source']}, prop['scene'], prop['text'][:120])
        asset = self.to_library('world_plan', f"תוכנית עולם · גרסה {version}: {prop['text'][:60]}", {'plan': prop['plan']}, prop['world_id'])
        self.index_built(prop['world_id'], 'world_plan', f"אבן דרך: גרסת עולם {version}", f"שינוי: {prop['text'][:300]}. " + ' '.join(summarize(prop['plan'])), 'world', 'fantasy.world_planner', asset)
        self.store.resolve_plan_proposal(pid, 'APPLIED')
        return {'status': 'APPLIED', 'version': version}

    def revert_world(self, wid, version):
        found = self.store.world_version(wid, version)
        if found is None:
            return None
        plan, scene = found
        return self.store.save_world_version(wid, plan, scene, f'חזרה לגרסה {version}')

    def house_payload(self, wid, hid):
        world = self.store.world(wid)
        house = next((h for h in world['scene']['houses'] if h['id'] == hid), None) if world else None
        if house is None:
            return None
        rooms = house_rooms(house)
        designs = {}
        for room in rooms:
            key = f'{hid}__{room["id"]}'
            latest = self.store.room_latest(wid, key)
            if latest is None:
                self.store.save_room(wid, key, house_design(room, house, world['spec']), 'חדר ריק (ברירת מחדל)')
                latest = self.store.room_latest(wid, key)
            designs[room['id']] = latest['design']
        return {'house': house, 'rooms': rooms, 'designs': designs}

    def find_object(self, world, target):
        scene = world['scene']
        if target['type'] == 'palace':
            p = scene['palace']
            return {'id': 'palace', 'name': p.get('name', 'הארמון'), 'kind': 'palace', 'w': p['w'], 'd': p['d'], 'h': p['h'], 'state': 0.3}
        if target['type'] == 'landmark':
            return next((m for m in scene.get('landmarks', []) if m['id'] == target['id']), None)
        if target['type'] == 'tree':
            idx = int(target['id'])
            return {**scene['trees'][idx], 'id': f'tree{idx}'} if 0 <= idx < len(scene['trees']) else None
        if target['type'] == 'house':
            h = next((x for x in scene['houses'] if x['id'] == target['id']), None)
            return None if h is None else {**h, 'name': f"בית ({h['id']})", 'kind': 'house', 'h': h['floors'] * 3.1, 'state': h.get('grime', 0.3)}
        if target['type'] == 'placed':
            placed = next((o for o in self.store.objects(world['id']) if o['object_id'] == target['id']), None)
            return None if placed is None else {'id': target['id'], 'name': placed['params'].get('name', 'אובייקט מהספרייה'), 'kind': placed['params'].get('base_kind', 'generic'),
                                                **{k: placed['params'].get(k) for k in ('w', 'd', 'h', 'x', 'z', 'y', 'rot')}}
        return None

    def propose_object(self, wid, target, text, use_llm=True):
        world = self.store.world(wid)
        obj = self.find_object(world, target)
        if obj is None:
            return None
        deliver = 'fantasy.botanist' if target['type'] == 'tree' else 'fantasy.architect'
        oid_guess = obj['id'] if target['type'] != 'tree' else f"tree{target['id']}"
        params, source = self.link.run(deliver, lambda ctx: plan_object(target, obj, text, use_llm, context_text(ctx)), {'target': target, 'text': text},
                                       world_spec=world['spec'], query=f"{obj.get('name', '')} {obj.get('kind', '')} {text}", object_id=oid_guess, kind=obj.get('kind'))
        object_ctx = self.link.last
        oid = obj['id'] if target['type'] != 'tree' else f"tree{target['id']}"
        kind = 'tree' if target['type'] == 'tree' else ('palace' if target['type'] == 'palace' else obj['kind'])
        pid = self.store.add_object_proposal(wid, oid, kind, text, source, {**params, '_target': target})
        engine = 'עץ מפורט (דפדפן)' if kind == 'tree' else 'Blender'
        return {'id': pid, 'object_id': oid, 'kind': kind, 'name': obj.get('name', kind), 'params': params, 'source': source, 'engine': engine, 'supported': True, 'deliver': public(object_ctx)}

    def resolve_object(self, pid, action):
        prop = self.store.object_proposal(pid)
        if prop is None or prop['status'] != 'PENDING':
            return None
        if action != 'apply':
            self.store.resolve_object_proposal(pid, 'REJECTED')
            return {'status': 'REJECTED'}
        wid = prop['world_id']
        world = self.store.world(wid)
        params = {k: v for k, v in prop['params'].items() if k != '_target'}
        target = prop['params'].get('_target') or {'type': 'landmark', 'id': prop['object_id']}
        obj = self.find_object(world, target)
        model = None
        if prop['kind'] != 'tree':
            model = self.link.run('fantasy.blender_builder', lambda: build_model(prop['kind'], obj, params, self.store.path.parent / 'models' / wid, world['spec'].get('condition', {}).get('decay', 0.3)), {'blender': prop['kind'], 'object': prop['object_id']})
        stored = {**params, **({'x': obj.get('x'), 'z': obj.get('z'), 'y': obj.get('y'), 'rot': obj.get('rot'), 'w': obj.get('w'), 'd': obj.get('d'), 'h': obj.get('h'), 'name': obj.get('name'), 'base_kind': obj.get('kind')} if target['type'] == 'placed' else {})}
        version = self.store.save_object(wid, prop['object_id'], 'placed' if target['type'] == 'placed' else prop['kind'], stored, model)
        self.store.resolve_object_proposal(pid, 'APPLIED')
        url = f'/models/{wid}/{model}' if model else None
        asset = self.to_library('tree' if prop['kind'] == 'tree' else 'model', f"{obj.get('name', prop['kind'])} · גרסה {version}", {**params, 'object_kind': prop['kind'], 'model': url, 'w': obj.get('w'), 'd': obj.get('d'), 'h': obj.get('h')}, wid)
        desc = '; '.join(f'{k}={v}' for k, v in params.items() if k not in ('notes', 'additions'))
        adds = ', '.join(f"{a['kind']} {a['position']}" for a in params.get('additions') or [])
        self.index_built(wid, prop['kind'], f"{obj.get('name', prop['kind'])} (גרסה {version})", f"{params.get('notes', '')} פרטים: {desc}. תוספות: {adds or 'אין'}. דגם: {url or 'עץ בדפדפן'}",
                         prop['object_id'], 'fantasy.botanist' if prop['kind'] == 'tree' else 'fantasy.blender_builder', asset)
        return {'status': 'APPLIED', 'object_id': prop['object_id'], 'kind': 'placed' if target['type'] == 'placed' else prop['kind'], 'model': url, 'params': stored, 'version': version}

    def to_library(self, kind, name, params, wid):
        return self.store.save_asset(kind, name, params, wid)

    def index_built(self, wid, kind, title, text, object_id, deliver_id, asset_id):
        world = self.store.world(wid)
        period = period_of(world['spec'] if world else {})

        def work():
            doc = self.rag.add(period, 'built', title, text, f"נבנה ב־{DELIVERS[deliver_id]['title']} · עולם: {world['name'] if world else wid}", (kind, 'built'), object_id)
            for rel, dst in (('built_by', f'deliver:{deliver_id}'), ('describes', f'object:{object_id}'), ('in_period', f'period:{period}'), ('in_world', f'world:{wid}'),
                             ('stored_as', f'asset:{asset_id}' if asset_id else None)):
                dst and self.rag.link(doc, rel, dst)
            for r in (self.link.last or {}).get('related', []) if (self.link.last or {}).get('deliver') == deliver_id else []:
                self.rag.link(doc, 'related_to', r['id'])
            row = dict(self.store.one('SELECT * FROM rag_docs WHERE id=?', (doc,)))
            self.link.context(deliver_id, row)
            self.link.context('fantasy.librarian', row)
            return doc

        return self.link.run('fantasy.librarian', work, {'index': title, 'object': object_id})

    def knowledge(self, wid, object_id=None):
        world = self.store.world(wid)
        period = period_of(world['spec'])
        built = [dict(r) for r in self.store.q('SELECT id, title, text, source, ref, created_at FROM rag_docs WHERE collection=? AND kind=? ORDER BY created_at DESC LIMIT 60', (period, 'built'))]
        facts = [dict(r) for r in self.store.q('SELECT id, title, source FROM rag_docs WHERE collection=? AND kind=?', (period, 'fact'))]
        links = self.rag.links_of(f'object:{object_id}') if object_id else []
        runs = [dict(r) for r in self.store.q('SELECT * FROM deliver_runs ORDER BY finished_at DESC LIMIT 25')]
        return {'period': period, 'facts': facts, 'built': built, 'links': links, 'runs': runs,
                'delivers': [{'id': k, 'title': v['title'], 'model': v['model'], 'rag': v['rag']} for k, v in DELIVERS.items()], 'manager_link': self.link.enabled}

    def library(self):
        return self.store.assets()

    def use_library(self, wid, asset_id, target=None, place=None, room_key=None):
        asset = next((a for a in self.store.assets() if a['id'] == asset_id), None)
        if asset is None:
            return None
        p = asset['params']
        if asset['kind'] == 'room' and room_key:
            design = copy.deepcopy(p['design'])
            current = self.store.room_latest(wid, room_key)
            if current:
                design.update({k: current['design'][k] for k in ('id', 'name', 'w', 'd', 'h') if k in current['design']})
                design = designer.layout(design)
            version = self.store.save_room(wid, room_key, design, f"מהספרייה: {asset['name']}")
            return {'kind': 'room', 'version': version, 'design': design}
        if asset['kind'] == 'tree' and target and target.get('type') == 'tree':
            oid = f"tree{target['id']}"
            version = self.store.save_object(wid, oid, 'tree', p, None)
            return {'kind': 'tree', 'object_id': oid, 'params': p, 'model': None, 'version': version}
        if asset['kind'] == 'model' and target and target.get('type') in ('landmark', 'palace', 'house', 'placed'):
            world = self.store.world(wid)
            obj = self.find_object(world, target)
            oid = obj['id'] if obj else target.get('id')
            version = self.store.save_object(wid, oid, p.get('object_kind', 'model'), {k: v for k, v in p.items() if k != 'model'}, p['model'].rsplit('/', 1)[-1] if p.get('model') else None)
            return {'kind': p.get('object_kind'), 'object_id': oid, 'model': p.get('model'), 'params': p, 'version': version}
        if asset['kind'] in ('model', 'tree') and place:
            world = self.store.world(wid)
            placed = [{**o['params'], 'w': o['params'].get('w', 4), 'd': o['params'].get('d', 4)} for o in self.store.objects(wid) if o['kind'] == 'placed']
            spot = free_spot(world['scene'], float(place.get('x', 0)), float(place.get('z', 0)), float(p.get('w', 4 if asset['kind'] == 'tree' else 8)), float(p.get('d', 4 if asset['kind'] == 'tree' else 8)),
                             float(place.get('rot', 0)), placed)
            if spot is None:
                return {'kind': 'none', 'error': 'אין מקום פנוי במפה ליד הנקודה הזו (רחובות, בתים או מים) — בחרו מקום אחר'}
            place = {**place, 'x': spot['x'], 'z': spot['z'], 'y': height_at(world['scene'], spot['x'], spot['z']), 'map_moved': spot['moved']}
            oid = 'placed_' + asset_id + '_' + str(int(place.get('x', 0))) + '_' + str(int(place.get('z', 0)))
            stored = {**p, **place, 'name': asset['name'], 'base_kind': p.get('object_kind', asset['kind']), 'asset_id': asset_id}
            version = self.store.save_object(wid, oid, 'placed', stored, p['model'].rsplit('/', 1)[-1] if p.get('model') else None)
            return {'kind': 'placed', 'object_id': oid, 'model': p.get('model'), 'params': stored, 'version': version}
        return {'kind': 'none', 'error': 'האובייקט מהספרייה לא מתאים לבחירה הזו'}

    def lookup(self, kind):
        return self.store.latest_asset(kind)

    def propose_reconstruction(self, wid, room_id, text):
        current = self.store.room_latest(wid, room_id)['design']
        spec = legacy_spec(self.store.world(wid)['spec'])
        comps = [{'key': 'reconstruct', 'type': 'reconstruct', 'action': 'set', 'selected': True,
                  'label': 'שחזור היסטורי של דומוס פלאוויה: ' + ' · '.join(r['name'] for r in DOMUS_FLAVIA_ROOMS)}]
        comps += [{'key': f"info:{r['id']}", 'type': 'info', 'action': 'set', 'selected': True, 'label': f"{r['name']} — {DOMUS_FLAVIA_DESIGNS[r['id']]['notes']}"} for r in DOMUS_FLAVIA_ROOMS]
        pid = self.store.add_proposal(wid, room_id, text, 'historical:domus_flavia', comps)
        preview_room = DOMUS_FLAVIA_ROOMS[0]
        return {'id': pid, 'components': comps, 'source': 'שחזור לפי מקורות היסטוריים', 'notes': DOMUS_FLAVIA_SOURCES,
                'preview': historical_design(preview_room, spec), 'preview_room': preview_room, 'current': current}

    def apply_reconstruction(self, wid):
        world = self.store.world(wid)
        spec = legacy_spec(world['spec'])
        scene = world['scene']
        scene['palace']['rooms'] = copy.deepcopy(DOMUS_FLAVIA_ROOMS)
        scene['palace']['historical_rooms'] = 'domus_flavia'
        plan = world['spec']
        self.store.save_world_version(wid, plan, scene, 'שחזור היסטורי של פנים הארמון — דומוס פלאוויה')
        versions = {}
        for r in DOMUS_FLAVIA_ROOMS:
            design = historical_design(r, spec)
            versions[r['id']] = self.store.save_room(wid, r['id'], design, 'שחזור היסטורי')
            self.to_library('room', f"חדר היסטורי: {r['name']}", {'design': design}, wid)
        self.to_library('interior_set', 'פנים הארמון — דומוס פלאוויה (שחזור היסטורי)', {'rooms': DOMUS_FLAVIA_ROOMS}, wid)
        return versions

    def propose(self, wid, room_id, text, use_llm=True):
        world = self.store.world(wid)
        if '__' not in room_id and world and is_rome(world['spec']) and any(w in text.lower() for w in RECONSTRUCT_WORDS):
            return self.propose_reconstruction(wid, room_id, text)
        latest = self.store.room_latest(wid, room_id)
        if latest is None:
            return None
        design = latest['design']

        def work(ctx):
            comps, source, notes = designer.propose(design, text, self.lookup, use_llm, context_text(ctx))
            return {'components': comps, 'source': source, 'notes': notes}

        result = self.link.run('fantasy.interior_designer', work, {'room': room_id, 'text': text}, world_spec=world['spec'], query=text, object_id=f'room:{room_id}', kind='room')
        designer_ctx = self.link.last
        pid = self.store.add_proposal(wid, room_id, text, result['source'], result['components'])
        preview = designer.apply_components(design, result['components'], self.lookup)
        return {'id': pid, 'components': result['components'], 'source': result['source'], 'notes': result['notes'], 'preview': preview, 'current': design, 'deliver': public(designer_ctx)}

    def preview(self, pid, selected):
        prop = self.store.proposal(pid)
        latest = self.store.room_latest(prop['world_id'], prop['room_id'])
        comps = [c for c in prop['components'] if c['key'] in selected]
        return designer.apply_components(latest['design'], comps, self.lookup)

    def resolve(self, pid, action, selected, scopes):
        prop = self.store.proposal(pid)
        if prop is None or prop['status'] != 'PENDING':
            return None
        if action != 'apply':
            self.store.resolve_proposal(pid, 'REJECTED')
            return {'status': 'REJECTED'}
        wid, room_id = prop['world_id'], prop['room_id']
        comps = [c for c in prop['components'] if c['key'] in selected]
        if any(c['type'] == 'reconstruct' for c in comps):
            versions = self.link.run('fantasy.palace_historian', lambda: self.apply_reconstruction(wid), {'reconstruct': 'domus_flavia'}, world_spec=self.store.world(wid)['spec'], query='Domus Flavia palace rooms')
            for r in DOMUS_FLAVIA_ROOMS:
                self.index_built(wid, 'room', f"חדר היסטורי: {r['name']}", DOMUS_FLAVIA_DESIGNS[r['id']]['notes'], f"room:{r['id']}", 'fantasy.palace_historian', None)
            self.store.resolve_proposal(pid, 'APPLIED')
            return {'status': 'APPLIED', 'design': None, 'versions': versions, 'reconstructed': True}
        comps = [c for c in comps if c['type'] not in ('info',)]
        surface, items = designer.split_scopes(comps)
        summary = designer.describe(comps)
        saved = {}

        def work():
            current = self.store.room_latest(wid, room_id)['design']
            design = designer.apply_components(current, comps, self.lookup)
            saved[room_id] = self.store.save_room(wid, room_id, design, summary)
            if 'building' in scopes and surface:
                building = room_id.split('__')[0] if '__' in room_id else None
                same = lambda rid: rid != room_id and ((rid.split('__')[0] == building) if building else '__' not in rid)
                for other_id in [rid for rid in self.store.rooms_latest(wid) if same(rid)]:
                    other = self.store.room_latest(wid, other_id)['design']
                    saved[other_id] = self.store.save_room(wid, other_id, designer.apply_components(other, surface), f'מהחדר {room_id}: ' + designer.describe(surface))
            if 'houses' in scopes:
                win = next((c for c in comps if c['type'] == 'windows' and c.get('style')), None)
                if win:
                    world = self.store.world(wid)
                    world['scene']['styles']['window'] = win['style']
                    for house in world['scene']['houses']:
                        house['window'] = win['style']
                    self.store.save_scene(wid, world['scene'])
                    self.store.event(wid, 'houses_window_style', {'style': win['style']})
            if 'library' in scopes:
                for comp in comps:
                    self.save_comp_asset(wid, comp, design)
            self.to_library('room', f"חדר: {design.get('name', room_id)} · {summary[:50]}", {'design': design}, wid)
            return {'status': 'APPLIED', 'design': design, 'versions': saved}

        result = self.link.run('fantasy.interior_designer', work, {'apply': pid, 'scopes': scopes})
        self.store.resolve_proposal(pid, 'APPLIED')
        design = result['design']
        self.index_built(wid, 'room', f"חדר: {design.get('name', room_id)}", f"{summary}. רצפה {design['floor']['material']}, קירות {design['walls']['material']} {design['walls']['color']}, תקרה {design['ceiling']['style']}, "
                         f"{len(design['items'])} פריטים: {', '.join(sorted({it['kind'] for it in design['items']}))}", f'room:{room_id}', 'fantasy.interior_designer', None)
        return result

    def save_comp_asset(self, wid, comp, design):
        t = comp['type']
        if t == 'windows':
            self.store.save_asset('window', 'חלון ' + (design['windows']['style'] or ''), copy.deepcopy(design['windows']), wid)
        elif t == 'floor':
            self.store.save_asset('floor', comp['label'], copy.deepcopy(design['floor']), wid)
        elif t == 'walls':
            self.store.save_asset('walls', comp['label'], copy.deepcopy(design['walls']), wid)
        elif t == 'item':
            sample = next((it for it in design['items'] if it['kind'] == comp['kind']), None)
            if sample:
                params = {k: sample[k] for k in ('w', 'd', 'h', 'color', 'material', 'name') if k in sample}
                self.store.save_asset(comp['kind'], f"{sample.get('name', comp['kind'])} · {params.get('color')}", params, wid)

    def revert(self, wid, room_id, version):
        design = self.store.room_version(wid, room_id, version)
        if design is None:
            return None
        self.store.save_room(wid, room_id, design, f'חזרה לגרסה {version}')
        return design
