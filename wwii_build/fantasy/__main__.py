import argparse
import json
import urllib.request

from .deliver_link import DeliverLink
from .server import PORT, App
from .service import Service


def main():
    ap = argparse.ArgumentParser(prog='python -m wwii_build.fantasy')
    ap.add_argument('command', choices=['serve', 'register'], nargs='?', default='serve')
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('--manager-db', default=None)
    args = ap.parse_args()
    link = DeliverLink(args.manager_db or 'auto')
    if args.command == 'register':
        if not link.enabled:
            print('no manager db: pass --manager-db or write its path to ~/.wwii-fantasy/manager_db.txt')
            return
        print('backup:', link.backup())
        service = Service(link=link)
        print(f'registered {link.register()} delivers; rag docs: {len(service.rag.docs(["rome_late_antiquity"]))}')
        return
    try:
        info = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health', timeout=2).read())
    except OSError:
        info = None
    if info and info.get('service') == 'fantasy-world-builder':
        print(f'Fantasy World Builder already running: http://127.0.0.1:{args.port}/')
        return
    app = App(Service(link=link), args.port)
    print(f'Fantasy World Builder: http://127.0.0.1:{args.port}/')
    app.serve()


main()
