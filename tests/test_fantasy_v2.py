import tempfile
import unittest
from pathlib import Path

from wwii_build.fantasy.basemap import place_names, rome_basemap, rome_plan_defaults
from wwii_build.fantasy.builder import generate
from wwii_build.fantasy.deliver_link import DeliverLink
from wwii_build.fantasy.plan import describe_changes, normalize, rules_plan
from wwii_build.fantasy.service import Service
from wwii_build.fantasy.store import Store

PROMPT = 'עיר עם נהר רחב שחוצה את העיר מצפון לדרום, ארמון על גבעה במזרח, רובע של בתי עץ אדומים במערב וקולוסיאום בדרום, ומסביב חומות'


class PlanRules(unittest.TestCase):
    def test_layout_words_become_placements(self):
        plan, explicit = rules_plan(PROMPT)
        self.assertEqual(plan['water']['rivers'][0]['from'], 'n')
        self.assertEqual(plan['water']['rivers'][0]['to'], 's')
        self.assertEqual(plan['water']['rivers'][0]['via'], 'center')
        self.assertEqual(plan['palace']['at'], 'hill_e')
        self.assertEqual(plan['districts'][0]['at'], 'w')
        self.assertEqual(plan['districts'][0]['style']['material'], 'wood')
        self.assertEqual(plan['landmarks'][0], {'kind': 'amphitheater', 'at': 's', 'name': ''})
        self.assertTrue(plan['city']['walls'])
        self.assertIn('water.rivers', explicit)

    def test_rome_and_decay_words(self):
        plan, explicit = rules_plan('רומא מיד אחרי הנפילה, המבנים קיימים אבל לא מתוחזקים, שעת שקיעה')
        self.assertEqual(plan['basemap'], 'rome_476')
        self.assertGreater(plan['condition']['decay'], 0.5)
        self.assertGreater(plan['condition']['overgrowth'], 0.5)
        self.assertEqual(plan['time_of_day'], 'golden')

    def test_normalize_rejects_unknown_values(self):
        plan = normalize({'terrain': {'kind': 'moon'}, 'style': {'roof': 'banana', 'wall_colors': ['red', '#AABBCC']}, 'palace': {'at': 'nowhere'}})
        self.assertEqual(plan['terrain']['kind'], 'mountains')
        self.assertEqual(plan['style']['roof'], 'gable')
        self.assertEqual(plan['style']['wall_colors'], ['#aabbcc'])
        self.assertEqual(plan['palace']['at'], 'center')


class RomeProjectMap(unittest.TestCase):
    def test_monuments_sit_where_history_puts_them(self):
        bm = rome_basemap()
        named = bm['named']
        colosseum, palatine, capitol, island = named['colosseum'], named['palatine'], named['capitoline'], named['tiber_island']
        self.assertGreater(colosseum[0], palatine[0])
        self.assertLess(capitol[1], palatine[1])
        self.assertLess(island[0], capitol[0])
        self.assertAlmostEqual(abs(colosseum[0] - island[0]), 1210, delta=60)

    def test_rome_scene_has_river_bridges_and_landmarks(self):
        plan = normalize(rome_plan_defaults(), place_names({'basemap': 'rome_476'}))
        plan['seed'] = 476
        scene = generate(plan)
        self.assertEqual(scene['rivers'][0]['name'], 'הטיבר')
        self.assertGreaterEqual(len(scene['bridges']), 5)
        kinds = {m['kind'] for m in scene['landmarks']}
        self.assertTrue({'amphitheater', 'circus', 'temple', 'triumphal_arch', 'pantheon'} <= kinds)
        self.assertGreater(len(scene['houses']), 800)
        self.assertTrue(any(h['ruin'] for h in scene['houses']))


class ProceduralPlacement(unittest.TestCase):
    def test_palace_east_and_river_through_city(self):
        plan = normalize(rules_plan(PROMPT)[0])
        plan['seed'] = 7
        scene = generate(plan)
        self.assertGreater(scene['palace']['x'], 30)
        xs = [p[0] for p in scene['rivers'][0]['pts']]
        zs = [p[1] for p in scene['rivers'][0]['pts']]
        self.assertLess(zs[0], -200)
        self.assertGreater(zs[-1], 200)
        self.assertLess(abs(sum(xs) / len(xs)), 80)
        self.assertTrue(scene['walls'])
        west = [h for h in scene['houses'] if h['district'] == 'd0']
        self.assertTrue(west and sum(h['x'] for h in west) / len(west) < 0)
        self.assertTrue(all(h['material'] == 'wood' for h in west))
        self.assertTrue(scene['map']['clean'])


class WorldEditing(unittest.TestCase):
    def test_prompt_edit_creates_version_and_moves_palace(self):
        service = Service(Store(Path(tempfile.mkdtemp()) / 'f.db'), DeliverLink(None))
        wid = service.create_world('rome', 'רומא אחרי הנפילה', False, None, (), 'rome_476')
        before = service.store.world(wid)['scene']['palace']
        prop = service.propose_plan(wid, 'הוסף מגדלור בדרום', None, False)
        self.assertTrue(prop['changes'])
        result = service.resolve_plan(prop['id'], 'apply')
        self.assertEqual(result['version'], 2)
        after = service.store.world(wid)['scene']
        self.assertTrue(any(m['kind'] == 'lighthouse' for m in after['landmarks']))
        self.assertEqual(after['palace']['x'], before['x'])
        self.assertEqual(service.revert_world(wid, 1), 3)
        self.assertFalse(any(m['kind'] == 'lighthouse' for m in service.store.world(wid)['scene']['landmarks']))

    def test_describe_changes_lists_paths(self):
        lines = describe_changes({'palace': {'at': 'palatine'}}, {'palace': {'at': 'aventine'}})
        self.assertEqual(len(lines), 1)
        self.assertIn('aventine', lines[0])


if __name__ == '__main__':
    unittest.main()


class DarkAgeAndDetail(unittest.TestCase):
    def setUp(self):
        self.service = Service(Store(Path(tempfile.mkdtemp()) / 'f.db'), DeliverLink(None))
        self.wid = self.service.create_world('rome', 'רומא אחרי הנפילה', False, None, (), 'rome_476')

    def test_dark_age_content(self):
        scene = self.service.store.world(self.wid)['scene']
        kinds = {m['kind'] for m in scene['landmarks']}
        self.assertTrue({'market_stalls', 'church', 'lime_kiln', 'vegetable_garden'} <= kinds)
        self.assertTrue(scene['decor']['boats'] and scene['decor']['mills'] and scene['decor']['animals'])

    def test_house_rooms_are_created_and_designed(self):
        house = next(h for h in self.service.store.world(self.wid)['scene']['houses'] if not h['ruin'])
        payload = self.service.house_payload(self.wid, house['id'])
        room = payload['rooms'][0]['id']
        prop = self.service.propose(self.wid, f"{house['id']}__{room}", 'הוסף שולחן ורצפת שיש', False)
        result = self.service.resolve(prop['id'], 'apply', [c['key'] for c in prop['components']], ['room'])
        self.assertEqual(result['versions'][f"{house['id']}__{room}"], 2)

    def test_palace_reconstruction_only_on_request(self):
        before = [r['id'] for r in self.service.store.world(self.wid)['scene']['palace']['rooms']]
        prop = self.service.propose(self.wid, 'entrance', 'שחזר את הארמון כפי שהיה באמת', False)
        self.assertEqual(prop['components'][0]['type'], 'reconstruct')
        self.service.resolve(prop['id'], 'apply', [c['key'] for c in prop['components']], ['room'])
        after = [r['id'] for r in self.service.store.world(self.wid)['scene']['palace']['rooms']]
        self.assertNotEqual(before, after)
        self.assertIn('aula_regia', after)
        self.assertTrue(self.service.store.room_latest(self.wid, 'peristyle'))

    def test_tree_detail_uses_species_facts(self):
        scene = self.service.store.world(self.wid)['scene']
        idx = next(i for i, t in enumerate(scene['trees']) if t['kind'] == 'umbrella_pine')
        prop = self.service.propose_object(self.wid, {'type': 'tree', 'id': str(idx)}, 'פרט את העץ', False)
        self.assertEqual(prop['params']['crown_shape'], 'umbrella')
        self.assertGreaterEqual(prop['params']['trunk_ratio'], 0.55)
        result = self.service.resolve_object(prop['id'], 'apply')
        self.assertEqual(result['kind'], 'tree')
        self.assertEqual(self.service.store.objects(self.wid)[0]['object_id'], f'tree{idx}')


class DeliverSystem(unittest.TestCase):
    def test_builds_run_through_delivers_with_period_rag_and_links(self):
        folder = Path(tempfile.mkdtemp())
        link = DeliverLink(str(folder / 'mgr.db'))
        service = Service(Store(folder / 'f.db'), link)
        self.assertEqual(link.register(), 13)
        wid = service.create_world('rome', 'רומא אחרי הנפילה', False, None, (), 'rome_476')
        scene = service.store.world(wid)['scene']
        idx = next(i for i, t in enumerate(scene['trees']) if t['kind'] == 'umbrella_pine')
        prop = service.propose_object(wid, {'type': 'tree', 'id': str(idx)}, 'איך נראה עץ האורן הזה באמת', False)
        self.assertEqual(prop['deliver']['deliver'], 'fantasy.botanist')
        self.assertTrue(any('pine' in f['title'].lower() for f in prop['deliver']['facts']))
        service.resolve_object(prop['id'], 'apply')
        second = service.propose_object(wid, {'type': 'tree', 'id': str(idx)}, 'עוד פרטים על העץ', False)
        self.assertTrue(second['deliver']['related'])
        runs = {r['deliver_id']: r for r in link.db.q('SELECT deliver_id, detail_json, cost_usd FROM deterministic_deliver_runs')}
        self.assertTrue({'fantasy.world_planner', 'fantasy.world_generator', 'fantasy.botanist', 'fantasy.librarian'} <= set(runs))
        self.assertEqual({r['cost_usd'] for r in runs.values()}, {0.0})
        sources = link.db.q("SELECT origin_kind, deliver_id FROM context_sources WHERE origin_kind LIKE 'fantasy_%'")
        self.assertTrue(any(s['origin_kind'] == 'fantasy_built' and s['deliver_id'] == 'fantasy.botanist' for s in sources))
        self.assertTrue(any(s['origin_kind'] == 'fantasy_rag' for s in sources))
        links = service.rag.links_of(f'object:tree{idx}')
        self.assertTrue(any(l['rel'] == 'describes' for l in links))
        caps = link.db.q("SELECT group_name FROM deliver_capabilities WHERE deliver_id='fantasy.architect'")
        self.assertEqual({c['group_name'] for c in caps}, {'model', 'rag'})


class GloryRomeAndLife(unittest.TestCase):
    def test_glory_era_is_detected_and_clean(self):
        self.assertEqual(rules_plan('אני רוצה את רומא בתפארתה עם אנשים')[0]['basemap'], 'rome_315')
        self.assertEqual(rules_plan('רומא מיד אחרי הנפילה')[0]['basemap'], 'rome_476')
        bm = rome_basemap('rome_315')
        kinds = {m['kind'] for m in bm['landmarks']}
        self.assertFalse(kinds & {'church', 'lime_kiln', 'vegetable_garden'})
        self.assertIn('baths_constantine', {m['id'] for m in bm['landmarks']})
        self.assertEqual(bm['mills'], [])
        self.assertLess(rome_plan_defaults('rome_315')['condition']['decay'], 0.1)

    def test_climate_plan_by_month(self):
        from wwii_build.fantasy.life import climate_plan
        c = climate_plan(1, 'night')
        self.assertEqual(len(c['by_month']), 12)
        self.assertTrue(all(abs(sum(m) - 1.0) < 1e-6 for m in c['by_month']))
        self.assertGreater(c['by_month'][0][c['kinds'].index('snow')], 0)
        self.assertEqual(c['by_month'][6][c['kinds'].index('snow')], 0)
        self.assertEqual(c['start_hour'], 22.0)

    def test_living_rome_runs_through_delivers(self):
        from wwii_build.fantasy.objects import blender_binary
        if not blender_binary():
            self.skipTest('Blender is not installed')
        folder = Path(tempfile.mkdtemp())
        link = DeliverLink(str(folder / 'mgr.db'))
        service = Service(Store(folder / 'f.db'), link)
        link.register()
        wid = service.create_world('rome', 'רומא בתפארתה, הכל חי', False)
        world = service.store.world(wid)
        life = world['scene']['life']
        self.assertEqual(world['spec']['basemap'], 'rome_315')
        self.assertEqual(world['scene']['stats']['ruins'], 0)
        self.assertEqual(life['agents'], 2600)
        self.assertGreaterEqual(len(life['markets']), 6)
        self.assertGreater(life['carts']['night'], life['carts']['day'])
        self.assertIn('Lex Julia', life['carts']['rule'])
        self.assertEqual(len(life['population']['types']), 20)
        self.assertTrue(all((folder / 'models' / 'population' / 'rome_imperial' / t['file']).exists() for t in life['population']['types']))
        runs = {r['deliver_id'] for r in link.db.q('SELECT deliver_id FROM deterministic_deliver_runs')}
        self.assertTrue({'fantasy.costume_designer', 'fantasy.character_builder', 'fantasy.climate_master', 'fantasy.life_director'} <= runs)
        self.assertEqual(len(service.store.assets('character')), 20)
        self.assertTrue(any('clothing' in f['tags'] for f in service.rag.search('toga senator purple stripe', ['rome_imperial'], 3)))
        service.build_life(wid)
        self.assertEqual(len(service.store.assets('character')), 20)

    def test_mcp_server_speaks_json_rpc(self):
        import io
        import json
        import sys
        from wwii_build.fantasy import mcp_server
        out = io.StringIO()
        real = sys.stdout
        tools = mcp_server.Tools()
        tools._service = Service(Store(Path(tempfile.mkdtemp()) / 'f.db'), DeliverLink(None))
        sys.stdout = out
        try:
            mcp_server.handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}})
            mcp_server.handle(tools, {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            mcp_server.handle(tools, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            mcp_server.handle(tools, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'list_delivers', 'arguments': {}}})
        finally:
            sys.stdout = real
        lines = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual([l['id'] for l in lines], [1, 2, 3])
        self.assertEqual(lines[0]['result']['serverInfo']['name'], 'fantasy-world-builder')
        self.assertIn('create_world', {t['name'] for t in lines[1]['result']['tools']})
        self.assertEqual(len(lines[2]["result"]["structuredContent"]["delivers"]), 13)


class MapFirst(unittest.TestCase):
    def test_glory_map_is_dense_and_clean(self):
        from wwii_build.fantasy.builder import build_scene, survey_map
        from wwii_build.fantasy.cartography import conflicts, free_spot, house_box, inside
        plan = normalize(rome_plan_defaults('rome_315'), place_names({'basemap': 'rome_315'}))
        plan['seed'] = 5
        site = survey_map(plan)
        self.assertTrue(site['report']['clean'])
        self.assertGreater(len(site['houses']), 5000)
        self.assertGreater(site['report']['filled_buildings'], 2000)
        scene = build_scene(site)
        self.assertEqual(scene['map'], site['report'])
        h = scene['houses'][100]
        spot = free_spot(scene, h['x'], h['z'], 6, 6)
        self.assertIsNotNone(spot)
        self.assertGreater(spot['moved'], 0)
        self.assertFalse(any(inside(house_box(x), spot['x'], spot['z']) for x in scene['houses']))

    def test_old_rome_roads_never_cross_buildings(self):
        from wwii_build.fantasy.builder import survey_map
        plan = normalize(rome_plan_defaults('rome_476'), place_names({'basemap': 'rome_476'}))
        plan['seed'] = 9
        site = survey_map(plan)
        self.assertEqual(site['report']['remaining_conflicts']['street_through_building'], 0)
        self.assertTrue(site['report']['clean'])
