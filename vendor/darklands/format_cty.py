# Source: vvendigo/Darklands (MIT) — unchanged, Python 3 compatible as-is
import os
from struct import pack, unpack
from .utils import cstrim, encode_dl_bytes, tchars

city_types = ('Free City', 'Ruled City', 'Capital')
CITY_CONTENT_FLAGS = (
    'has_kloster', 'has_slums', 'has_unknown1', 'has_cathedral', 'has_unknown2',
    'has_no_fortress', 'has_town_hall', 'has_polit', 'has_constant1', 'has_constant2',
    'has_constant3', 'has_constant4', 'has_docks', 'has_unknown3', 'has_pawnshop',
    'has_university',
)


class City:
    def __init__(self):
        self.short_name = ''
        self.name = ''
        self.city_size = None
        self.entry_coords = None
        self.exit_coords = None
        self.dock_destinations = []
        self.coast = None
        self.unknown_cd_1 = None
        self.pseudo_ordinal = None
        self.city_type = None
        self.unknown_cd_2 = None
        self.unknown_cd_3 = None
        self.city_contents = {}
        self.unknown_cd_4 = None
        self.qual_blacksmith = None
        self.qual_merchant = None
        self.qual_swordsmith = None
        self.qual_armorer = None
        self.qual_unk1 = None
        self.qual_bowyer = None
        self.qual_tinker = None
        self.qual_unk2 = None
        self.qual_clothing = None
        self.qual_unk3 = None
        self.unknown_cd_5 = None
        self.unknown_cd_6 = None
        self.unknown_cd_5_6 = None
        self.leader_name = None
        self.ruler_name = None
        self.unknown = None
        self.center_name = None
        self.town_hall_name = None
        self.fortress_name = None
        self.cathedral_name = None
        self.church_name = None
        self.market_name = None
        self.unknown2 = None
        self.slum_name = None
        self.unknown3 = None
        self.pawnshop_name = None
        self.kloster_name = None
        self.inn_name = None
        self.university_name = None
        self.str_dock_destinations = []
        self.str_city_type = ''

    def from_data(self, data):
        pos = 0
        self.short_name = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.name       = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.city_size, = unpack('H', data[pos:pos + 2]); pos += 2
        self.entry_coords = unpack('HH', data[pos:pos + 4]); pos += 4
        self.exit_coords  = unpack('HH', data[pos:pos + 4]); pos += 4
        dests = []
        for i in range(0, 4):
            tgt, = unpack('H', data[pos:pos + 2]); pos += 2
            if tgt != 0xffff:
                dests.append(tgt)
        self.dock_destinations = dests
        self.coast,       = unpack('H', data[pos:pos + 2]); pos += 2
        self.unknown_cd_1,= unpack('H', data[pos:pos + 2]); pos += 2
        self.pseudo_ordinal, = unpack('H', data[pos:pos + 2]); pos += 2
        self.city_type,   = unpack('H', data[pos:pos + 2]); pos += 2
        self.unknown_cd_2,= unpack('H', data[pos:pos + 2]); pos += 2
        self.unknown_cd_3,= unpack('H', data[pos:pos + 2]); pos += 2
        city_contents = (unpack('B', data[pos:pos + 1])[0] << 8) | unpack('B', data[pos + 1:pos + 2])[0]; pos += 2
        buildings = {}
        for i, o in enumerate(CITY_CONTENT_FLAGS):
            buildings[o] = 1 if city_contents & (1 << (15 - i)) else 0
        self.city_contents = buildings
        self.bin_city_contents = bin(city_contents)
        self.unknown_cd_4, = unpack('H', data[pos:pos + 2]); pos += 2
        self.qual_blacksmith, = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_merchant,   = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_swordsmith, = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_armorer,    = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_unk1,       = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_bowyer,     = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_tinker,     = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_unk2,       = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_clothing,   = unpack('B', data[pos:pos + 1]); pos += 1
        self.qual_unk3,       = unpack('B', data[pos:pos + 1]); pos += 1
        self.unknown_cd_5,    = unpack('B', data[pos:pos + 1]); pos += 1
        self.unknown_cd_6,    = unpack('B', data[pos:pos + 1]); pos += 1
        self.unknown_cd_5_6,  = unpack('H', data[pos - 2:pos])
        self.leader_name     = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.ruler_name      = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.unknown         = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.center_name     = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.town_hall_name  = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.fortress_name   = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.cathedral_name  = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.church_name     = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.market_name     = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.unknown2        = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.slum_name       = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.unknown3        = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.pawnshop_name   = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.kloster_name    = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.inn_name        = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32
        self.university_name = cstrim(unpack('32s', data[pos:pos + 32])[0]); pos += 32

    def __str__(self):
        return '%s%s: %s' % (
            tchars(self.name),
            ('/' + tchars(self.short_name)) if self.name != self.short_name else '',
            str(self.entry_coords),
        )


def read_file(fname):
    data = open(fname, 'rb').read()
    pos = 0
    cnt = unpack('B', data[pos:pos + 1])[0]; pos += 1
    cities = []
    for i in range(0, cnt):
        c = City()
        c.from_data(data[pos:pos + 622])
        cities.append(c)
        pos += 622
    for c in cities:
        c.str_dock_destinations = ', '.join([cities[d].short_name for d in c.dock_destinations])
        c.str_city_type = city_types[c.city_type]
    return cities


def readData(dlPath='DL'):
    return read_file(os.path.join(dlPath, 'DARKLAND.CTY'))


def _pad_cstr(text, length):
    return encode_dl_bytes(text or '')[:length - 1].ljust(length, b'\x00')


def _city_contents_mask(city):
    contents = city.city_contents if hasattr(city, 'city_contents') else city.get('city_contents', {})
    mask = 0
    for i, flag in enumerate(CITY_CONTENT_FLAGS):
        if contents.get(flag):
            mask |= (1 << (15 - i))
    return mask


def write_file(fname, cities):
    data = bytearray()
    data += bytes([len(cities) & 0xFF])
    for city in cities:
        row = bytearray()
        row += _pad_cstr(city.short_name, 32)
        row += _pad_cstr(city.name, 32)
        row += pack('<H', int(city.city_size) & 0xFFFF)
        row += pack('<HH', int(city.entry_coords[0]) & 0xFFFF, int(city.entry_coords[1]) & 0xFFFF)
        row += pack('<HH', int(city.exit_coords[0]) & 0xFFFF, int(city.exit_coords[1]) & 0xFFFF)

        dests = list(city.dock_destinations)[:4]
        while len(dests) < 4:
            dests.append(0xFFFF)
        for dst in dests:
            row += pack('<H', int(dst) & 0xFFFF)

        row += pack('<H', int(city.coast) & 0xFFFF)
        row += pack('<H', int(city.unknown_cd_1) & 0xFFFF)
        row += pack('<H', int(city.pseudo_ordinal) & 0xFFFF)
        row += pack('<H', int(city.city_type) & 0xFFFF)
        row += pack('<H', int(city.unknown_cd_2) & 0xFFFF)
        row += pack('<H', int(city.unknown_cd_3) & 0xFFFF)
        row += pack('>H', _city_contents_mask(city) & 0xFFFF)
        row += pack('<H', int(city.unknown_cd_4) & 0xFFFF)
        row += bytes([
            int(city.qual_blacksmith) & 0xFF,
            int(city.qual_merchant) & 0xFF,
            int(city.qual_swordsmith) & 0xFF,
            int(city.qual_armorer) & 0xFF,
            int(city.qual_unk1) & 0xFF,
            int(city.qual_bowyer) & 0xFF,
            int(city.qual_tinker) & 0xFF,
            int(city.qual_unk2) & 0xFF,
            int(city.qual_clothing) & 0xFF,
            int(city.qual_unk3) & 0xFF,
            int(city.unknown_cd_5) & 0xFF,
            int(city.unknown_cd_6) & 0xFF,
        ])
        row += _pad_cstr(city.leader_name, 32)
        row += _pad_cstr(city.ruler_name, 32)
        row += _pad_cstr(city.unknown, 32)
        row += _pad_cstr(city.center_name, 32)
        row += _pad_cstr(city.town_hall_name, 32)
        row += _pad_cstr(city.fortress_name, 32)
        row += _pad_cstr(city.cathedral_name, 32)
        row += _pad_cstr(city.church_name, 32)
        row += _pad_cstr(city.market_name, 32)
        row += _pad_cstr(city.unknown2, 32)
        row += _pad_cstr(city.slum_name, 32)
        row += _pad_cstr(city.unknown3, 32)
        row += _pad_cstr(city.pawnshop_name, 32)
        row += _pad_cstr(city.kloster_name, 32)
        row += _pad_cstr(city.inn_name, 32)
        row += _pad_cstr(city.university_name, 32)
        data += row

    with open(fname, 'wb') as fh:
        fh.write(data)
