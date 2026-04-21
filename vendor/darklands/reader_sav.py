"""
reader_sav.py — Darklands save-game binary parser.

Offsets verified against illusium77/darklandscompanion C# source and the
original format spec at web.archive.org/web/20091112110231/
  http://wallace.net/darklands/formats/dksaveXX.sav.html

File layout
-----------
  0x000  SaveHeader  (declared size 0x188, but SaveParty starts inside it)
  0x0EF  SaveParty
           +0x00 / 2   numberOfCharacters
           +0x02 / 2   numberOfDefinedCharacters
           +0x04 / 10  partyIds (5 × word)
           +0x9A       character records  →  file offset 0x189
  0x189 + N*0x22A   SaveEvents  (N = numberOfDefinedCharacters)

SaveHeader field offsets (relative to file start 0x00)
-------------------------------------------------------
  0x00 / 12   currentLocationName
  0x15 / 23   label  (save-slot label)
  0x68 /  8   Date struct
  0x70 /  6   Money  { florins:2, groschen:2, pfennigs:2 }
  0x7A /  2   reputation  (signed word)
  0x7C /  2   locationId
  0x8C /  2   bankNotes   (separate cash-on-hand word)
  0x92 /  2   philosopherStone

Character record (0x22A = 554 bytes each, base = 0x189 + i*0x22A)
------------------------------------------------------------------
  +0x12 / 2   age
  +0x15 / 1   equippedShield     (byte id)
  +0x17 / 1   gender             (0 = female, 1 = male)
  +0x22 / 1   equippedMissileType
  +0x25 / 25  fullName
  +0x3E / 11  shortName
  +0x49 / 1   gearWeight
  +0x4B / 1   equippedVitalType      (body armour type id)
  +0x4C / 1   equippedLegType        (leg armour type id)
  +0x4F / 1   equippedVitalQuality
  +0x50 / 1   equippedLegQuality
  +0x51 / 1   equippedWeaponType
  +0x58 / 1   equippedWeaponQuality
  +0x5A / 1   equippedMissileQuality
  +0x5B / 1   equippedShieldQuality
  +0x5C / 1   equippedShieldType
  +0x5D / 7   currentAttributes  { end str agl per int chr df }
  +0x64 / 7   maxAttributes
  +0x6B / 19  skills             (one byte per skill, see SKILL_KEYS)
  +0x7E / 2   numberOfItems
  +0x80 / 20  saintBitmask
  +0x94 / 22  formulaeBitmask
  +0xAA / 384 itemList           (64 × 6-byte Item records)

Item record (6 bytes)
---------------------
  +0 / 2   id
  +2 / 1   type
  +3 / 1   quality
  +4 / 1   quantity
  +5 / 1   weight

SaveEvents (base = 0x189 + numberOfDefinedCharacters * 0x22A)
-------------------------------------------------------------
  +0x00 / 2   numberOfEvents
  +0x02       events[]   (each 0x30 = 48 bytes)
              then numberOfLocations word, locations[] (each 0x3A = 58 bytes)

Event record (0x30 bytes)
-------------------------
  +0x00 / 2   unknown0
  +0x02 / 8   createDate
  +0x0A / 8   unknownDate
  +0x12 / 8   expireDate
  +0x1A / 2   questGiver
  +0x1C / 2   destinationLocationId
  +0x1E / 2   sourceLocationId
  +0x2E / 2   requiredItemId
"""
import os
import struct
from .utils import decode_dl_text, encode_dl_bytes

# ── constants ─────────────────────────────────────────────────────────────────
PARTY_OFFSET     = 0x0EF
FIRST_CHAR_OFF   = 0x189   # = PARTY_OFFSET + 0x9A
CHAR_SIZE        = 0x22A   # 554 bytes per character in save file
EVENT_SIZE       = 0x30    # 48 bytes per event
LOCATION_SIZE    = 0x3A    # 58 bytes per location

ATTR_KEYS = ('end', 'str', 'agl', 'per', 'int', 'chr', 'df')
SKILL_KEYS = (
    'wEdg', 'wImp', 'wFll', 'wPol', 'wThr',
    'wBow', 'wMsl', 'alch', 'relg', 'virt',
    'spkC', 'spkL', 'r_w',  'heal', 'artf',
    'stlh', 'strW', 'ride', 'wdWs',
)

EQUIP_FIELDS = (
    # (field_name, char_offset, is_quality)
    ('weapon_type',          0x51, False),
    ('weapon_quality',       0x58, True),
    ('vital_type',           0x4B, False),   # body armour
    ('vital_quality',        0x4F, True),
    ('leg_type',             0x4C, False),
    ('leg_quality',          0x50, True),
    ('shield_type',          0x5C, False),
    ('shield_quality',       0x5B, True),
    ('missile_type',         0x22, False),
    ('missile_quality',      0x5A, True),
)


# ── low-level helpers ─────────────────────────────────────────────────────────

def _u8(data, off):
    return data[off]

def _u16(data, off):
    return struct.unpack_from('<H', data, off)[0]

def _i16(data, off):
    return struct.unpack_from('<h', data, off)[0]

def _cstr(data, off, length):
    raw = data[off:off + length]
    end = raw.find(b'\x00')
    if end >= 0:
        raw = raw[:end]
    return decode_dl_text(raw.decode('latin-1', errors='replace').rstrip())

def _write_cstr(buf, off, s, length):
    encoded = encode_dl_bytes(s)[:length - 1]
    for i in range(length):
        buf[off + i] = 0
    buf[off:off + len(encoded)] = encoded


# ── parsers ───────────────────────────────────────────────────────────────────

def read_header(data):
    return {
        'location':    _cstr(data, 0x00, 12),
        'label':       _cstr(data, 0x15, 23),
        'curr_date_raw': data[0x68:0x70],
        'florins':     _u16(data, 0x70),
        'groschen':    _u16(data, 0x72),
        'pfennigs':    _u16(data, 0x74),
        'reputation':  _i16(data, 0x7A),
        'location_id': _u16(data, 0x7C),
        'coords':      (_u16(data, 0x7E), _u16(data, 0x80)),
        'curr_menu':   _u16(data, 0x82),
        'prev_menu':   _u16(data, 0x8A),
        'bank_notes':  _u16(data, 0x8C),
        'philo_stone': _u16(data, 0x92),
        'party_order_indices': [data[0x9B + i] for i in range(5)],
        'party_leader_index': data[0xA1],
    }


def read_character(data, base):
    b = base
    char = {
        'age':        _u16(data, b + 0x12),
        'gender':     _u8(data,  b + 0x17),   # 0 = female, 1 = male
        'full_name':  _cstr(data, b + 0x25, 25),
        'short_name': _cstr(data, b + 0x3E, 11),
        'gear_weight': _u8(data, b + 0x49),
        'attrs_cur':  {},
        'attrs_max':  {},
        'skills':     {},
        'num_items':  _u16(data, b + 0x7E),
        'items':      [],
        # Equipment — individual bytes
        'equip': {
            'weapon_type':      _u8(data, b + 0x51),
            'weapon_quality':   _u8(data, b + 0x58),
            'vital_type':       _u8(data, b + 0x4B),
            'vital_quality':    _u8(data, b + 0x4F),
            'leg_type':         _u8(data, b + 0x4C),
            'leg_quality':      _u8(data, b + 0x50),
            'shield_type':      _u8(data, b + 0x5C),
            'shield_quality':   _u8(data, b + 0x5B),
            'missile_type':     _u8(data, b + 0x22),
            'missile_quality':  _u8(data, b + 0x5A),
        },
        # Saints and formulae bitmasks (raw)
        'saint_bits':   data[b + 0x80 : b + 0x94],
        'formula_bits': data[b + 0x94 : b + 0xAA],
    }

    for i, k in enumerate(ATTR_KEYS):
        char['attrs_cur'][k] = _u8(data, b + 0x5D + i)
        char['attrs_max'][k] = _u8(data, b + 0x64 + i)
    for i, k in enumerate(SKILL_KEYS):
        char['skills'][k] = _u8(data, b + 0x6B + i)

    # Inventory: 64 slots × 6 bytes at char+0xAA
    item_base = b + 0xAA
    for i in range(64):
        off = item_base + i * 6
        item_id = _u16(data, off)
        char['items'].append({
            'id':       item_id,
            'type':     _u8(data, off + 2),
            'quality':  _u8(data, off + 3),
            'quantity': _u8(data, off + 4),
            'weight':   _u8(data, off + 5),
            '_slot':    i,
        })
    return char


def read_party(data):
    b = PARTY_OFFSET
    n_chars   = _u16(data, b + 0x00)
    n_defined = _u16(data, b + 0x02)
    party_ids = [_u16(data, b + 0x04 + i * 2) for i in range(5)]
    chars = []
    for i in range(n_defined):
        chars.append(read_character(data, FIRST_CHAR_OFF + i * CHAR_SIZE))
    return {
        'n_chars':    n_chars,
        'n_defined':  n_defined,
        'party_ids':  party_ids,
        'characters': chars,
    }


def read_events(data, party):
    """Parse SaveEvents section (after all defined character records)."""
    b = FIRST_CHAR_OFF + party['n_defined'] * CHAR_SIZE
    if b + 2 > len(data):
        return [], []

    n_events = _u16(data, b)
    b += 2
    events = []
    for _ in range(n_events):
        if b + EVENT_SIZE > len(data):
            break
        raw = data[b:b + EVENT_SIZE]
        events.append({
            'create_date_raw':       raw[0x02:0x0A],
            'expire_date_raw':       raw[0x12:0x1A],
            'quest_giver':           _u16(raw, 0x1A),
            'dest_location_id':      _u16(raw, 0x1C),
            'src_location_id':       _u16(raw, 0x1E),
            'required_item_id':      _u16(raw, 0x2E),
            '_raw':                  raw,
        })
        b += EVENT_SIZE

    # Locations follow
    locations = []
    if b + 2 <= len(data):
        n_locs = _u16(data, b)
        b += 2
        for _ in range(n_locs):
            if b + LOCATION_SIZE > len(data):
                break
            raw = data[b:b + LOCATION_SIZE]
            locations.append({
                'type':             _u16(raw, 0x00),
                'local_reputation': _i16(raw, 0x12),
                'name':             _cstr(raw, 0x26, 20),
                '_raw':             raw,
            })
            b += LOCATION_SIZE

    return events, locations


def read_file(path):
    """Return (header, party, events, locations, raw_bytes)."""
    with open(path, 'rb') as f:
        data = f.read()
    header             = read_header(data)
    party              = read_party(data)
    events, locations  = read_events(data, party)
    return header, party, events, locations, data


# ── writers ───────────────────────────────────────────────────────────────────

def write_file(path, header, party, original_data):
    """Patch modified fields back into a copy of original_data and write."""
    buf = bytearray(original_data)

    # Header
    _write_cstr(buf, 0x15, header['label'],      23)
    struct.pack_into('<H', buf, 0x70, header['florins']     & 0xFFFF)
    struct.pack_into('<H', buf, 0x72, header['groschen']    & 0xFFFF)
    struct.pack_into('<H', buf, 0x74, header['pfennigs']    & 0xFFFF)
    struct.pack_into('<h', buf, 0x7A, max(-32768, min(32767, header['reputation'])))
    struct.pack_into('<H', buf, 0x7C, header.get('location_id', 0) & 0xFFFF)
    coords = header.get('coords', (0, 0))
    struct.pack_into('<H', buf, 0x7E, int(coords[0]) & 0xFFFF)
    struct.pack_into('<H', buf, 0x80, int(coords[1]) & 0xFFFF)
    struct.pack_into('<H', buf, 0x82, header.get('curr_menu', 0) & 0xFFFF)
    struct.pack_into('<H', buf, 0x8A, header.get('prev_menu', 0) & 0xFFFF)
    struct.pack_into('<H', buf, 0x8C, header['bank_notes']  & 0xFFFF)
    struct.pack_into('<H', buf, 0x92, header['philo_stone'] & 0xFFFF)
    order = list(header.get('party_order_indices', [0, 1, 2, 3, 4]))[:5]
    while len(order) < 5:
        order.append(len(order))
    for i, idx in enumerate(order):
        buf[0x9B + i] = int(idx) & 0xFF
    buf[0xA1] = int(header.get('party_leader_index', 0)) & 0xFF

    # Characters
    for i, char in enumerate(party['characters']):
        b = FIRST_CHAR_OFF + i * CHAR_SIZE
        struct.pack_into('<H', buf, b + 0x12, char['age'] & 0xFFFF)
        buf[b + 0x17] = char['gender'] & 0xFF
        _write_cstr(buf, b + 0x25, char['full_name'],  25)
        _write_cstr(buf, b + 0x3E, char['short_name'], 11)
        for j, k in enumerate(ATTR_KEYS):
            buf[b + 0x5D + j] = char['attrs_cur'][k] & 0xFF
            buf[b + 0x64 + j] = char['attrs_max'][k] & 0xFF
        for j, k in enumerate(SKILL_KEYS):
            buf[b + 0x6B + j] = char['skills'][k] & 0xFF
        # Equipment bytes
        eq = char.get('equip', {})
        for fname, foff, _ in EQUIP_FIELDS:
            if fname in eq:
                buf[b + foff] = eq[fname] & 0xFF
        # Items
        item_base = b + 0xAA
        for slot, item in enumerate(char['items'][:64]):
            off = item_base + slot * 6
            struct.pack_into('<H', buf, off,     item['id']       & 0xFFFF)
            buf[off + 2] = item['type']     & 0xFF
            buf[off + 3] = item['quality']  & 0xFF
            buf[off + 4] = item['quantity'] & 0xFF
            buf[off + 5] = item['weight']   & 0xFF

    with open(path, 'wb') as f:
        f.write(buf)


# ── file discovery ────────────────────────────────────────────────────────────

def find_save_files(dl_path):
    """Return [(display_name, full_path)] for all .SAV files near dl_path."""
    search_dirs = [dl_path]
    parent = os.path.dirname(dl_path)
    if parent and parent != dl_path:
        search_dirs.append(parent)
        for sub_name in ('SAVE', 'SAVES', 'save', 'saves'):
            sub = os.path.join(parent, sub_name)
            if os.path.isdir(sub):
                search_dirs.append(sub)
    # Also check SAVES/ directly inside dl_path
    for sub_name in ('SAVE', 'SAVES', 'save', 'saves'):
        sub = os.path.join(dl_path, sub_name)
        if os.path.isdir(sub):
            search_dirs.append(sub)

    seen = set()
    results = []
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.upper().endswith('.SAV'):
                full = os.path.normpath(os.path.join(d, fname))
                key  = full.upper()   # case-insensitive dedup on Windows
                if key not in seen:
                    seen.add(key)
                    results.append((fname, full))
    return results
