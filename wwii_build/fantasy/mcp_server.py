import json
import sys
import traceback

from .deliver_link import DELIVERS, model_for

PROTOCOL = '2025-06-18'
SERVER = {'name': 'fantasy-world-builder', 'title': 'Fantasy World Builder', 'version': '1.1.0'}
INSTRUCTIONS = ('Builds and edits 3D historical worlds (Rome c. 315 in its glory, Rome c. 476 after the fall, or free fantasy) through the Deliver system. '
                'Every build runs through a deliver with a local model and period RAG; nothing uses paid tokens. Worlds are viewed at http://127.0.0.1:8790.')

ERAS = {'rome_315': 'רומא בתפארתה (315)', 'rome_476': 'רומא אחרי הנפילה (476)'}
WEATHER = ['clear', 'cloudy', 'rain', 'storm', 'fog', 'snow']


def obj(props, required=()):
    return {'type': 'object', 'properties': props, 'required': list(required), 'additionalProperties': False}


TOOLS = [
    {'name': 'list_worlds', 'title': 'List worlds', 'description': 'List the worlds that were built, newest first.', 'inputSchema': obj({}), 'annotations': {'readOnlyHint': True}},
    {'name': 'create_world', 'title': 'Create a world',
     'description': 'Build a new world from a description (Hebrew or English). era "rome_315" = Rome in its glory with a living population, "rome_476" = Rome after the fall; omit for automatic. Runs the world planner, generator, costume designer, character builder (Blender), climate master and life director delivers.',
     'inputSchema': obj({'description': {'type': 'string'}, 'name': {'type': 'string'}, 'era': {'type': 'string', 'enum': list(ERAS)}, 'use_llm': {'type': 'boolean', 'description': 'use the local vision model for planning (slower, about a minute)'}}, ['description'])},
    {'name': 'world_summary', 'title': 'World summary', 'description': 'Stats of a world: houses, streets, landmarks, the life plan (people, markets, carts, litters, boats), the climate plan and which delivers built it.',
     'inputSchema': obj({'world_id': {'type': 'string'}}, ['world_id']), 'annotations': {'readOnlyHint': True}},
    {'name': 'rebuild_life', 'title': 'Rebuild life', 'description': 'Re-run the costume designer, character builder, climate master and life director for a Rome world.',
     'inputSchema': obj({'world_id': {'type': 'string'}, 'use_llm': {'type': 'boolean', 'description': 'let the local model choose period dyes for the costumes'}}, ['world_id'])},
    {'name': 'propose_world_edit', 'title': 'Propose a world edit', 'description': 'Ask for a change to the world (e.g. "add a market near the Colosseum"). Returns a proposal with the list of changes; nothing changes until resolve_world_edit applies it.',
     'inputSchema': obj({'world_id': {'type': 'string'}, 'text': {'type': 'string'}, 'use_llm': {'type': 'boolean'}}, ['world_id', 'text'])},
    {'name': 'resolve_world_edit', 'title': 'Apply or reject an edit', 'description': 'Apply or reject a pending world edit proposal.',
     'inputSchema': obj({'proposal_id': {'type': 'string'}, 'action': {'type': 'string', 'enum': ['apply', 'reject']}}, ['proposal_id', 'action']), 'annotations': {'destructiveHint': False}},
    {'name': 'set_world_clock', 'title': 'Set time and weather', 'description': 'Set the date (day and month), hour (0-24) and weather the world opens with next time it is loaded.',
     'inputSchema': obj({'world_id': {'type': 'string'}, 'hour': {'type': 'number', 'minimum': 0, 'maximum': 24}, 'month': {'type': 'integer', 'minimum': 0, 'maximum': 11, 'description': '0 = January'},
                         'day': {'type': 'integer', 'minimum': 1, 'maximum': 31}, 'weather': {'type': 'string', 'enum': WEATHER}}, ['world_id'])},
    {'name': 'search_knowledge', 'title': 'Search period knowledge', 'description': 'Search the period RAG (sourced facts and items already built).',
     'inputSchema': obj({'query': {'type': 'string'}, 'period': {'type': 'string', 'enum': ['rome_imperial', 'rome_late_antiquity', 'fantasy_generic']}, 'k': {'type': 'integer', 'minimum': 1, 'maximum': 12}}, ['query']),
     'annotations': {'readOnlyHint': True}},
    {'name': 'list_delivers', 'title': 'List delivers', 'description': 'The delivers of the fantasy builder with their model and RAG.', 'inputSchema': obj({}), 'annotations': {'readOnlyHint': True}},
    {'name': 'recent_runs', 'title': 'Recent deliver runs', 'description': 'The latest deliver runs (which deliver, model, seconds, RAG facts used).',
     'inputSchema': obj({'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}), 'annotations': {'readOnlyHint': True}},
    {'name': 'library', 'title': 'Library', 'description': 'Items stored in the library for reuse (characters, world plans, life plans, models, room designs).',
     'inputSchema': obj({'kind': {'type': 'string'}}), 'annotations': {'readOnlyHint': True}},
]


class Tools:
    def __init__(self):
        self._service = None

    @property
    def service(self):
        if self._service is None:
            from .service import Service
            self._service = Service()
        return self._service

    def list_worlds(self, args):
        return {'worlds': [{'id': w['id'], 'name': w['name'], 'description': w['description'][:160]} for w in self.service.store.list_worlds()]}

    def create_world(self, args):
        desc = args['description']
        era = args.get('era')
        wid = self.service.create_world(args.get('name') or '', desc, bool(args.get('use_llm', False)), None, (), era)
        return {'world_id': wid, **self.world_summary({'world_id': wid}), 'open': 'http://127.0.0.1:8790'}

    def world_summary(self, args):
        world = self.service.store.world(args['world_id'])
        if world is None:
            raise ValueError('world not found')
        scene = world['scene']
        life = scene.get('life') or {}
        out = {'name': world['name'], 'era': world['spec'].get('basemap'), 'stats': scene.get('stats'), 'condition': world['spec'].get('condition')}
        if life and not life.get('off'):
            out['life'] = {'label': life['label'], 'agents': life['agents'], 'types': [t['label'] for t in life['population']['types']], 'markets': [m['name'] for m in life['markets']],
                           'gatherings': len(life['gatherings']), 'carts': {'day': life['carts']['day'], 'night': life['carts']['night'], 'rule': life['carts']['rule']},
                           'litters': life['litters']['count'], 'boats': life['boats']['count'], 'night_patrols': life['night']['patrols'],
                           'climate': {'start_month': life['climate']['months_he'][life['climate']['start_month']], 'start_hour': life['climate']['start_hour'], 'notes': life['climate']['notes']},
                           'delivers': [{'deliver': d['deliver'], 'model': d['model'], 'rag': [f['title'] for f in d.get('facts', [])]} for d in life.get('delivers', []) if d]}
        return out

    def rebuild_life(self, args):
        life = self.service.build_life(args['world_id'], bool(args.get('use_llm', False)))
        if not life:
            raise ValueError('only historical Rome worlds have a life plan')
        return self.world_summary(args)

    def propose_world_edit(self, args):
        prop = self.service.propose_plan(args['world_id'], args['text'], None, bool(args.get('use_llm', False)))
        if prop is None:
            raise ValueError('world cannot be edited by plan')
        return {'proposal_id': prop['id'], 'changes': prop['changes'], 'source': prop['source'], 'summary': prop['summary'], 'deliver': prop.get('deliver')}

    def resolve_world_edit(self, args):
        result = self.service.resolve_plan(args['proposal_id'], args['action'])
        if result is None:
            raise ValueError('proposal is not pending')
        return result

    def set_world_clock(self, args):
        result = self.service.set_clock(args['world_id'], args.get('hour'), args.get('month'), args.get('day'), args.get('weather'))
        if result is None:
            raise ValueError('only historical Rome worlds have a clock')
        return result

    def search_knowledge(self, args):
        return {'results': self.service.rag.search(args['query'], [args.get('period', 'rome_imperial')], int(args.get('k', 5)))}

    def list_delivers(self, args):
        return {'delivers': [{'id': did, 'title': d['title'], 'model': model_for(d['model']), 'rag': d['rag'], 'tags': list(d['tags']), 'description': d['desc']} for did, d in DELIVERS.items()],
                'manager_db': self.service.link.db_path}

    def recent_runs(self, args):
        rows = self.service.store.q('SELECT * FROM deliver_runs ORDER BY finished_at DESC LIMIT ?', (int(args.get('limit', 20)),))
        return {'runs': [{'run_id': r['run_id'], 'deliver': r['deliver_id'], 'model': r['model'], 'detail': json.loads(r['detail_json'])} for r in rows]}

    def library(self, args):
        return {'items': [{'id': a['id'], 'kind': a['kind'], 'name': a['name']} for a in self.service.store.assets(args.get('kind'))][:200]}


def reply(msg_id, result=None, error=None):
    body = {'jsonrpc': '2.0', 'id': msg_id, **({'error': error} if error else {'result': result})}
    sys.stdout.write(json.dumps(body, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def handle(tools, msg):
    method = msg.get('method')
    msg_id = msg.get('id')
    params = msg.get('params') or {}
    if msg_id is None:
        return
    if method == 'initialize':
        reply(msg_id, {'protocolVersion': params.get('protocolVersion') or PROTOCOL, 'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': SERVER, 'instructions': INSTRUCTIONS})
    elif method == 'ping':
        reply(msg_id, {})
    elif method == 'tools/list':
        reply(msg_id, {'tools': TOOLS})
    elif method == 'tools/call':
        name = params.get('name')
        fn = getattr(tools, name, None) if name in {t['name'] for t in TOOLS} else None
        if fn is None:
            reply(msg_id, error={'code': -32602, 'message': f'unknown tool: {name}'})
            return
        try:
            data = fn(params.get('arguments') or {})
            reply(msg_id, {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False, default=str)}], 'structuredContent': data, 'isError': False})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            reply(msg_id, {'content': [{'type': 'text', 'text': f'error: {exc}'}], 'isError': True})
    else:
        reply(msg_id, error={'code': -32601, 'message': f'method not found: {method}'})


def main():
    tools = Tools()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply(None, error={'code': -32700, 'message': 'parse error'})
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            handle(tools, m)


if __name__ == '__main__':
    main()
