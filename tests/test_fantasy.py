import tempfile
import unittest
from pathlib import Path

from wwii_build.fantasy.city import generate_scene
from wwii_build.fantasy.deliver_link import DeliverLink
from wwii_build.fantasy.interpreter import interpret_room_rules, interpret_world
from wwii_build.fantasy.service import Service
from wwii_build.fantasy.store import Store

MOUNTAIN = 'עיר צפופה בהרים גבוהים וחדים, בתים מאבן עם גגות מחודדים וחלונות קמורים, שבילים מפותלים, מדרגות וגשרים, שלג על הגגות, אווירה קסומה'


class FantasyTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.service = Service(Store(Path(self.dir) / 'f.db'), DeliverLink(None))

    def test_description_drives_the_spec(self):
        spec = interpret_world(MOUNTAIN, use_llm=False)
        self.assertEqual(spec['terrain']['kind'], 'sharp_mountains')
        self.assertEqual(spec['architecture']['roof'], 'pointed')
        self.assertEqual(spec['architecture']['window'], 'arched')
        self.assertTrue(spec['climate']['snow_roofs'])
        self.assertTrue(spec['urban']['bridges'])
        self.assertEqual(spec['mood'], 'magical')

    def test_different_fantasies_give_different_worlds(self):
        tropical = interpret_world('עיר על חוף טרופי, עם עצי דקל ושלג על הגגות', use_llm=False)
        desert = interpret_world('עיר מדברית ובה ארמונות ומקורות מים', use_llm=False)
        self.assertEqual(tropical['climate']['vegetation'], 'tropical')
        self.assertTrue(tropical['climate']['snow_roofs'])
        self.assertEqual(desert['terrain']['kind'], 'desert')
        self.assertFalse(desert['water']['sea'])

    def test_scene_is_deterministic_and_populated(self):
        spec = interpret_world(MOUNTAIN, use_llm=False)
        a, b = generate_scene(spec), generate_scene(spec)
        self.assertEqual(a['heights'], b['heights'])
        self.assertGreater(len(a['houses']), 20)
        self.assertGreater(a['stats']['stairs'], 0)
        self.assertEqual(len(a['palace']['rooms']), 3)

    def test_room_parser_counts_and_colors(self):
        room = {'floor': {'material': 'stone'}, 'walls': {'material': 'stone', 'color': '#fff'}}
        comps = {c['key']: c for c in interpret_room_rules('שתי נברשות, שולחן עץ ארוך עם שמונה כיסאות, רצפת שיש ושטיח אדום', room)}
        self.assertEqual(comps['item:chandelier']['count'], 2)
        self.assertEqual(comps['item:chair']['count'], 8)
        self.assertIn('item:long_table', comps)
        self.assertEqual(comps['floor']['material'], 'marble')
        self.assertEqual(comps['item:rug']['color'], '#b3382c')

    def test_room_edit_persists_and_reverts(self):
        wid = self.service.create_world('t', MOUNTAIN, False)
        prop = self.service.propose(wid, 'great_hall', 'שולחן עץ ארוך עם ארבעה כיסאות ורצפת שיש', False)
        keys = [c['key'] for c in prop['components']]
        result = self.service.resolve(prop['id'], 'apply', keys, ['room', 'library'])
        self.assertEqual(result['versions']['great_hall'], 2)
        reopened = Service(Store(Path(self.dir) / 'f.db'), DeliverLink(None))
        design = reopened.world_payload(wid)['rooms']['great_hall']
        self.assertEqual(design['floor']['material'], 'marble')
        self.assertEqual(len([i for i in design['items'] if i['kind'] == 'chair']), 4)
        self.assertTrue(reopened.store.assets('long_table'))
        reopened.revert(wid, 'great_hall', 1)
        self.assertEqual(reopened.world_payload(wid)['rooms']['great_hall']['items'], [])

    def test_library_asset_is_reused(self):
        wid = self.service.create_world('t', MOUNTAIN, False)
        first = self.service.propose(wid, 'entrance', 'ארבעה פמוטים זהב', False)
        self.service.resolve(first['id'], 'apply', [c['key'] for c in first['components']], ['room', 'library'])
        second = self.service.propose(wid, 'great_hall', 'הוסף פמוטים', False)
        self.assertIn('asset', second['components'][0])

    def test_deliver_link_records_zero_cost_runs(self):
        link = DeliverLink(str(Path(self.dir) / 'mgr.db'))
        self.assertEqual(link.register(), 13)
        service = Service(Store(Path(self.dir) / 'g.db'), link)
        service.create_world('t', MOUNTAIN, False)
        rows = link.db.q('SELECT status, cost_usd FROM deterministic_deliver_runs')
        self.assertEqual({r['status'] for r in rows}, {'COMPLETED'})
        self.assertEqual({r['cost_usd'] for r in rows}, {0.0})


if __name__ == '__main__':
    unittest.main()
