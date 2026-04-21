# Source: vvendigo/Darklands (MIT) — unchanged, Python 3 compatible as-is
import os
import struct
from collections import OrderedDict
from .utils import bread, encode_dl_bytes, sread

_ITEM_FLAG_FIELDS = (
    ('is_edged', 'is_impact', 'is_polearm', 'is_flail', 'is_thrown', 'is_bow', 'is_metal_armor', 'is_shield'),
    ('is_unknown1', 'is_unknown2', 'is_component', 'is_potion', 'is_relic', 'is_horse', 'is_quest_1', 'is_const0_1'),
    ('is_lockpicks', 'is_light', 'is_arrow', 'is_const0_2', 'is_quarrel', 'is_ball', 'is_const0_3', 'is_quest_2'),
    ('is_throw_potion', 'is_const0_4', 'is_nonmetal_armor', 'is_missile_weapon', 'is_unknown3', 'is_music', 'is_const0_6', 'is_const0_7'),
    ('is_unknown4', 'is_unknown5', 'is_const0_8', 'is_const0_9', 'is_const0_10', 'is_const0_11', 'is_const0_12', 'is_unknown6'),
)


def readData(dlPath):
    fname = os.path.join(dlPath, 'DARKLAND.LST')
    data = open(fname, 'rb').read()
    itemCnt, saintCnt, formCnt = data[0], data[1], data[2]
    pos = 3

    items = []
    for i in range(0, itemCnt):
        c = OrderedDict()
        c['name']       = sread(data[pos:pos + 20]); pos += 20
        c['short_name'] = sread(data[pos:pos + 10]); pos += 10
        c['type']       = bread(data[pos:pos + 2]); pos += 2
        for f in _ITEM_FLAG_FIELDS:
            bits = data[pos]; pos += 1
            for b, n in enumerate(f):
                c[n] = True if bits & (1 << b) else False
        c['weight']   = data[pos]; pos += 1
        c['quality']  = data[pos]; pos += 1
        c['rarity']   = data[pos]; pos += 1
        c['unknown1'] = bread(data[pos:pos + 2]); pos += 2
        c['unknown2'] = bread(data[pos:pos + 2]); pos += 2
        c['value']    = bread(data[pos:pos + 2]); pos += 2
        items.append(c)

    saints = []
    for i in range(0, saintCnt):
        raw = bytearray()
        while data[pos]:
            raw.append(data[pos]); pos += 1
        pos += 1
        saints.append({'name': sread(raw)})
    for i in range(0, saintCnt):
        raw = bytearray()
        while data[pos]:
            raw.append(data[pos]); pos += 1
        pos += 1
        saints[i]['short_name'] = sread(raw)

    formulae = []
    for i in range(0, formCnt):
        raw = bytearray()
        while data[pos]:
            raw.append(data[pos]); pos += 1
        pos += 1
        formulae.append({'name': sread(raw)})
    for i in range(0, formCnt):
        raw = bytearray()
        while data[pos]:
            raw.append(data[pos]); pos += 1
        pos += 1
        formulae[i]['short_name'] = sread(raw)

    # read saints descriptions
    fname2 = os.path.join(dlPath, 'DARKLAND.SNT')
    data2 = open(fname2, 'rb').read()
    pos2 = 1
    for i in range(0, len(saints)):
        saints[i]['description'] = sread(data2[pos2:pos2 + 0x168])
        pos2 += 0x168

    return items, saints, formulae


def _encode_cstr(text, fixed_len):
    return encode_dl_bytes(text or '')[:fixed_len - 1].ljust(fixed_len, b'\x00')


def _flag_byte(item, names):
    bits = 0
    for bit, name in enumerate(names):
        if item.get(name):
            bits |= (1 << bit)
    return bits


def writeData(dlPath, items, saints, formulae):
    lst = bytearray()
    lst += bytes([len(items) & 0xFF, len(saints) & 0xFF, len(formulae) & 0xFF])

    for item in items:
        lst += _encode_cstr(item.get('name', ''), 20)
        lst += _encode_cstr(item.get('short_name', ''), 10)
        lst += struct.pack('<H', int(item.get('type', 0)) & 0xFFFF)
        for names in _ITEM_FLAG_FIELDS:
            lst.append(_flag_byte(item, names))
        lst.append(int(item.get('weight', 0)) & 0xFF)
        lst.append(int(item.get('quality', 0)) & 0xFF)
        lst.append(int(item.get('rarity', 0)) & 0xFF)
        lst += struct.pack('<H', int(item.get('unknown1', 0)) & 0xFFFF)
        lst += struct.pack('<H', int(item.get('unknown2', 0)) & 0xFFFF)
        lst += struct.pack('<H', int(item.get('value', 0)) & 0xFFFF)

    for key in ('name', 'short_name'):
        for saint in saints:
            lst += encode_dl_bytes(saint.get(key, '') or '') + b'\x00'

    for key in ('name', 'short_name'):
        for formula in formulae:
            lst += encode_dl_bytes(formula.get(key, '') or '') + b'\x00'

    with open(os.path.join(dlPath, 'DARKLAND.LST'), 'wb') as fh:
        fh.write(lst)

    snt = bytearray([len(saints) & 0xFF])
    for saint in saints:
        desc = encode_dl_bytes(saint.get('description', '') or '')[:0x167]
        snt += desc.ljust(0x168, b'\x00')
    with open(os.path.join(dlPath, 'DARKLAND.SNT'), 'wb') as fh:
        fh.write(snt)


if __name__ == '__main__':
    import sys
    from utils import itemStr
    dlPath = sys.argv[1] if len(sys.argv) > 1 else 'DL'
    items, saints, forms = readData(dlPath)
    for i, c in enumerate(items):
        print('#', i, '#'); print(itemStr(c))
    print()
    for i, c in enumerate(saints):
        print('#', i, '#'); print(itemStr(c))
    print()
    for i, c in enumerate(forms):
        print('#', i, '#'); print(itemStr(c))
