from .city import default_room_design


def house_rooms(house):
    w = max(4.0, house['w'] - 0.6)
    d = max(4.0, house['d'] - 0.6)
    h = 3.8
    if d >= 7.5 and w >= 6.5:
        front_d = round(d * 0.55, 2)
        back_d = round(d - front_d - 0.4, 2)
        return [
            {'id': 'front', 'name': 'החדר הקדמי' if house.get('type') != 'insula' else 'החנות (טברנה)', 'cx': 0.0, 'cz': 0.0, 'w': round(w, 2), 'd': front_d, 'h': h,
             'doors': [{'wall': 's', 'pos': 0.0, 'width': 1.8, 'exit': True}, {'wall': 'n', 'pos': 0.0, 'width': 1.6}]},
            {'id': 'back', 'name': 'החדר האחורי', 'cx': 0.0, 'cz': round(-(front_d / 2 + 0.4 + back_d / 2), 2), 'w': round(w, 2), 'd': back_d, 'h': h,
             'doors': [{'wall': 's', 'pos': 0.0, 'width': 1.6}]},
        ]
    return [{'id': 'front', 'name': 'החדר', 'cx': 0.0, 'cz': 0.0, 'w': round(w, 2), 'd': round(d, 2), 'h': h, 'doors': [{'wall': 's', 'pos': 0.0, 'width': 1.8, 'exit': True}]}]


def house_design(room, house, plan):
    roman = plan.get('basemap') in ('rome_476', 'rome_315') or plan.get('style', {}).get('material') == 'plaster'
    spec = {'architecture': {'material': house.get('material', 'plaster'), 'window': house.get('window', 'rect'), 'wall_color': '#c98d5a' if roman else None}}
    design = default_room_design(room, spec)
    design['floor'] = {'material': 'tile' if roman else 'wood', 'color': '#b79a6e' if roman else '#8a5a32'}
    design['windows']['count'] = 1
    design['windows']['size'] = 'small'
    design['ceiling'] = {'style': 'beams', 'color': '#cfc8b8'}
    design['door_north'] = any(d['wall'] == 'n' for d in room['doors'])
    return design
