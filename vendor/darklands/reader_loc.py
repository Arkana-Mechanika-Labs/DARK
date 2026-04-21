# Source: vvendigo/Darklands (MIT) — unchanged, Python 3 compatible as-is
import os
import struct
from collections import OrderedDict
from .utils import bread, encode_dl_bytes, sread

locTypes = (
    'city',
    'castle',
    'castle (Raubritter)',
    'monastery',
    'Teufelstein',
    'cave',
    'mines',
    '7',
    'village',
    'ruins of a village',
    'village2',
    '11', '12',
    'tomb',
    '14',
    "dragon's lair",
    'spring',
    'lake',
    'shrine',
    'cave2',
    'pagan altar',
    'witch sabbat',
    'Templar castle',
    'Hockkonig (Baphomet castle)',
    'alpine cave',
    'lady of the lake',
    "ruins of a Raubritter's castle",
)


def read_file(fname):
    data = open(fname, 'rb').read()
    pos = 0
    cnt = bread(data[pos:pos + 2]); pos += 2
    locs = []
    for i in range(0, cnt):
        c = OrderedDict()
        c['icon']         = bread(data[pos:pos + 2]); pos += 2
        c['str_loc_type'] = locTypes[c['icon']] if c['icon'] < len(locTypes) else str(c['icon'])
        c['unknown1']     = bread(data[pos:pos + 2]); pos += 2
        c['coords']       = (bread(data[pos:pos + 2]), bread(data[pos + 2:pos + 4])); pos += 4
        c['unknown2']     = bread(data[pos:pos + 2]); pos += 2
        c['unknown3']     = bread(data[pos:pos + 2]); pos += 2
        c['menu']         = bread(data[pos:pos + 2]); pos += 2
        c['unknown4']     = bread(data[pos:pos + 2]); pos += 2
        c['unknown5']     = data[pos]; pos += 1
        c['city_size']    = data[pos]; pos += 1
        c['local_rep']    = bread(data[pos:pos + 2]); pos += 2
        c['unknown6']     = data[pos]; pos += 1
        c['unknown7_c']   = bread(data[pos:pos + 3]); pos += 3
        c['inn_cache_idx']= bread(data[pos:pos + 2]); pos += 2
        c['unknown8_c']   = bread(data[pos:pos + 2]); pos += 2
        c['unknown9']     = bread(data[pos:pos + 2]); pos += 2
        c['unknown10_c']  = bread(data[pos:pos + 8]); pos += 8
        c['name']         = sread(data[pos:pos + 20]); pos += 20
        locs.append(c)
    return locs


def readData(dlPath):
    return read_file(os.path.join(dlPath, 'DARKLAND.LOC'))


def _write_cstr(buf, off, text, length):
    raw = encode_dl_bytes(text or "")[:length - 1]
    buf[off:off + length] = b'\x00' * length
    buf[off:off + len(raw)] = raw


def write_file(fname, locs):
    data = bytearray()
    data += struct.pack('<H', len(locs) & 0xFFFF)
    for loc in locs:
        row = bytearray(0x3A)
        struct.pack_into('<H', row, 0x00, int(loc.get('icon', 0)) & 0xFFFF)
        struct.pack_into('<H', row, 0x02, int(loc.get('unknown1', 0)) & 0xFFFF)
        x, y = loc.get('coords', (0, 0))
        struct.pack_into('<H', row, 0x04, int(x) & 0xFFFF)
        struct.pack_into('<H', row, 0x06, int(y) & 0xFFFF)
        struct.pack_into('<H', row, 0x08, int(loc.get('unknown2', 0)) & 0xFFFF)
        struct.pack_into('<H', row, 0x0A, int(loc.get('unknown3', 0)) & 0xFFFF)
        struct.pack_into('<H', row, 0x0C, int(loc.get('menu', 0)) & 0xFFFF)
        struct.pack_into('<H', row, 0x0E, int(loc.get('unknown4', 0)) & 0xFFFF)
        row[0x10] = int(loc.get('unknown5', 0xFF)) & 0xFF
        row[0x11] = int(loc.get('city_size', 1)) & 0xFF
        struct.pack_into('<h', row, 0x12, max(-32768, min(32767, int(loc.get('local_rep', 0)))))
        row[0x14] = int(loc.get('unknown6', 0)) & 0xFF

        u7 = loc.get('unknown7_c', b'\x19\x19\x19')
        if isinstance(u7, int):
            u7 = int(u7).to_bytes(3, 'little', signed=False)
        row[0x15:0x18] = bytes(u7)[:3].ljust(3, b'\x00')

        struct.pack_into('<H', row, 0x18, int(loc.get('inn_cache_idx', 0xFFFF)) & 0xFFFF)

        u8 = loc.get('unknown8_c', 0)
        if isinstance(u8, (bytes, bytearray)):
            row[0x1A:0x1C] = bytes(u8)[:2].ljust(2, b'\x00')
        else:
            struct.pack_into('<H', row, 0x1A, int(u8) & 0xFFFF)

        struct.pack_into('<H', row, 0x1C, int(loc.get('unknown9', 0)) & 0xFFFF)

        u10 = loc.get('unknown10_c', b'\x00' * 8)
        if isinstance(u10, int):
            u10 = int(u10).to_bytes(8, 'little', signed=False)
        row[0x1E:0x26] = bytes(u10)[:8].ljust(8, b'\x00')

        _write_cstr(row, 0x26, loc.get('name', ''), 20)
        data += row

    with open(fname, 'wb') as fh:
        fh.write(data)


if __name__ == '__main__':
    import sys
    from utils import itemStr
    dlPath = sys.argv[1] if len(sys.argv) > 1 else 'DL'
    locs = readData(dlPath)
    for i, c in enumerate(locs):
        print('#', i, '#')
        print(itemStr(dict(c)))
