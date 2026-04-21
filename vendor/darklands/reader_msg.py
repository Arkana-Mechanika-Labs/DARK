# Source: vvendigo/Darklands (MIT)
# Python 3 rewrite: clean bytes-based parser; fixes 0x1d crash and 0x15 dual-role.
from collections import OrderedDict
from pathlib import Path

# Option-type byte → label
CHOICE_TYPES = {0x15: 'STD', 0x10: 'PTN', 0x16: 'SNT', 0x06: 'BTL'}
CHOICE_TYPE_BYTES = {label: value for value, label in CHOICE_TYPES.items()}

# Bytes that end a text run or option entry
_BREAKS = frozenset({0x14, 0x0a})


def _decode(raw_bytes):
    """Decode raw bytes to str, keeping only printable latin-1."""
    return raw_bytes.decode('latin-1')


def vis(txt):
    """Flat human-readable render of a card content string (for quick inspection)."""
    out = []
    for ch in txt:
        o = ord(ch)
        if o == 0x14 or o == 0x0a:
            out.append('\n')
        elif o == 0x1d:
            out.append(' | ')
        elif o in CHOICE_TYPES:
            out.append(f'[{CHOICE_TYPES[o]}]')
        elif 0x20 <= o < 0x7f:
            out.append(ch)
        # else: skip other control bytes silently
    return ''.join(out)


def parseCard(raw):
    """
    Parse the null-terminated content of one MSG card.

    Parameters
    ----------
    raw : bytes or str (latin-1 encoded)
        The content bytes after the 5-byte card header and before the null terminator.

    Returns
    -------
    list of (str | list)
        * str  → a paragraph of plain text
        * list → [kind, dots, label]  or  [kind, dots]  or  [kind]
                 where kind ∈ {'STD','PTN','SNT','BTL'}
                 dots  = the "…" portion before the 0x1d separator
                 label = the option text after the 0x1d separator

    Binary format (from X.msg.xml):
        printable bytes   → paragraph text
        0x14 / 0x0a       → paragraph / line break (ends current segment)
        0x15/0x10/0x16/0x06 → option-type marker; starts a new option entry
        0x1d              → within an option: separates dots from label text
        0x00              → null terminator (not passed in)
    """
    if isinstance(raw, str):
        data = raw.encode('latin-1')
    else:
        data = bytes(raw)

    out = []
    i = 0
    n = len(data)

    def _collect_printable(stop_at):
        """Collect printable ASCII bytes until we hit stop_at bytes or a choice marker."""
        nonlocal i
        buf = []
        while i < n:
            b = data[i]
            if b in stop_at or b in CHOICE_TYPES:
                break
            if 0x20 <= b < 0x7f:
                buf.append(b)
            # other control bytes (stray 0x1d in text context etc.) are silently skipped
            i += 1
        return bytes(buf).decode('latin-1').strip()

    while i < n:
        b = data[i]

        if b in _BREAKS:
            # Bare break with no preceding content — skip
            i += 1

        elif b in CHOICE_TYPES:
            # ── Option entry ──────────────────────────────────────────────
            kind = CHOICE_TYPES[b]
            i += 1  # consume the marker byte

            # Collect "dots" portion (up to 0x1d separator or a break)
            stop_dots = _BREAKS | {0x1d}
            dots = _collect_printable(stop_dots)

            if i < n and data[i] == 0x1d:
                i += 1  # consume 0x1d
                # Collect label (up to break)
                label = _collect_printable(_BREAKS)
                out.append([kind, dots, label])
            elif dots:
                out.append([kind, dots])
            else:
                out.append([kind])

            # Consume trailing break if present
            if i < n and data[i] in _BREAKS:
                i += 1

        elif 0x20 <= b < 0x7f:
            # ── Text paragraph ────────────────────────────────────────────
            # Stop at breaks or at an option marker (so options aren't swallowed)
            para = _collect_printable(_BREAKS)
            if para:
                out.append(para)
            # Consume trailing break if present
            if i < n and data[i] in _BREAKS:
                i += 1

        else:
            # Unknown / unexpected control byte — skip
            i += 1

    return out


def readData(fname):
    """Read a .MSG file and return a list of card dicts."""
    raw = open(fname, 'rb').read()
    return readDataBytes(raw)


def readDataBytes(raw):
    """Read raw .MSG bytes and return a list of card dicts."""
    pos = 0
    card_cnt = raw[pos]; pos += 1
    cards = []
    for _ in range(card_cnt):
        c = OrderedDict()
        c['textOffsY'] = raw[pos]; pos += 1
        c['textOffsX'] = raw[pos]; pos += 1
        c['unknown1']  = raw[pos]; pos += 1
        c['textMaxX']  = raw[pos]; pos += 1
        c['unknown2']  = raw[pos]; pos += 1
        # Find null terminator
        end = raw.find(b'\x00', pos)
        if end < 0:
            end = len(raw)
        content = raw[pos:end]
        c['text']     = vis(content.decode('latin-1'))
        c['elements'] = parseCard(content)
        pos = end + 1
        cards.append(c)
    return cards


def _clean_text_bytes(text):
    if text is None:
        return b''
    if not isinstance(text, str):
        text = str(text)
    raw = text.encode('latin-1', errors='replace')
    out = bytearray()
    for b in raw:
        if b in (0x00, 0x06, 0x0A, 0x10, 0x14, 0x15, 0x16, 0x1D):
            continue
        if b >= 0x20:
            out.append(b)
    return bytes(out).rstrip()


def serializeCard(elements):
    out = bytearray()
    for element in elements:
        if isinstance(element, str):
            text = _clean_text_bytes(element)
            if text:
                out.extend(text)
                out.append(0x14)
            continue

        if not isinstance(element, (list, tuple)) or not element:
            continue

        kind = str(element[0]).upper()
        marker = CHOICE_TYPE_BYTES.get(kind)
        if marker is None:
            continue
        out.append(marker)

        dots = _clean_text_bytes(element[1] if len(element) > 1 else '')
        label = _clean_text_bytes(element[2] if len(element) > 2 else '')
        if dots:
            out.extend(dots)
        if label:
            out.append(0x1D)
            out.extend(label)
        out.append(0x14)

    if out and out[-1] == 0x14:
        out.pop()
    return bytes(out)


def writeData(fname, cards):
    Path(fname).write_bytes(writeBytes(cards))


def writeBytes(cards):
    payload = bytearray()
    payload.append(len(cards) & 0xFF)
    for card in cards:
        header = (
            int(card.get('textOffsY', 0)) & 0xFF,
            int(card.get('textOffsX', 0)) & 0xFF,
            int(card.get('unknown1', 0)) & 0xFF,
            int(card.get('textMaxX', 0)) & 0xFF,
            int(card.get('unknown2', 0)) & 0xFF,
        )
        payload.extend(header)
        content = serializeCard(card.get('elements', []))
        payload.extend(content)
        payload.append(0x00)
    return bytes(payload)


write_file = writeData
