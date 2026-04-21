# Source: vvendigo/Darklands (MIT) — Python 3 fix: binary reading + function wrapper
import os
import struct
from .utils import bread, sread


def _encode_name(name):
    raw = os.path.basename(str(name)).encode('ascii', errors='replace')[:12]
    return raw.ljust(12, b'\x00')


def readEntries(fname):
    """Return CAT entries as dicts with name, timestamp, size, offset, and data."""
    data = open(fname, 'rb').read()
    pos = 0
    cnt = bread(data[pos:pos + 2]); pos += 2
    entries = []
    for _ in range(cnt):
        name = sread(data[pos:pos + 12]); pos += 12
        timestamp = data[pos:pos + 4]; pos += 4
        size = bread(data[pos:pos + 4]); pos += 4
        offset = bread(data[pos:pos + 4]); pos += 4
        entries.append({
            'name': name,
            'timestamp': bytes(timestamp),
            'size': size,
            'offset': offset,
            'data': data[offset:offset + size],
        })
    return entries


def writeCat(fname, entries):
    """Write CAT archive from entry dicts with keys name, data, and optional timestamp."""
    count = len(entries)
    header_size = 2 + count * 24
    payload = bytearray()
    table = bytearray(struct.pack('<H', count))
    offset = header_size
    for entry in entries:
        name = _encode_name(entry['name'])
        timestamp = bytes(entry.get('timestamp', b'\x00\x00\x00\x00'))[:4].ljust(4, b'\x00')
        data = bytes(entry.get('data', b''))
        table.extend(name)
        table.extend(timestamp)
        table.extend(struct.pack('<I', len(data)))
        table.extend(struct.pack('<I', offset))
        payload.extend(data)
        offset += len(data)
    with open(fname, 'wb') as fh:
        fh.write(table)
        fh.write(payload)
    return fname


def extractAll(fname, ddir):
    """Extract all files from a CAT archive to ddir. Returns list of (filename, size)."""
    data = open(fname, 'rb').read()  # Python 3: read as bytes
    pos = 0
    cnt = bread(data[pos:pos + 2]); pos += 2

    extracted = []
    for i in range(0, cnt):
        fn = sread(data[pos:pos + 12]); pos += 12
        pos += 4  # timestamp (skipped)
        dataLen = bread(data[pos:pos + 4]); pos += 4
        dataOffs = bread(data[pos:pos + 4]); pos += 4
        out_path = os.path.join(ddir, fn)
        with open(out_path, 'wb') as fh:
            fh.write(data[dataOffs:dataOffs + dataLen])
        extracted.append((fn, dataLen))

    return extracted


def listContents(fname):
    """List files in a CAT archive without extracting. Returns list of (filename, size)."""
    data = open(fname, 'rb').read()
    pos = 0
    cnt = bread(data[pos:pos + 2]); pos += 2
    entries = []
    for i in range(0, cnt):
        fn = sread(data[pos:pos + 12]); pos += 12
        pos += 4  # timestamp
        dataLen = bread(data[pos:pos + 4]); pos += 4
        dataOffs = bread(data[pos:pos + 4]); pos += 4
        entries.append((fn, dataLen, dataOffs))
    return entries


def extractOneToBytes(fname, entry_name):
    """Extract a single named file from a CAT archive, returning its raw bytes.
    Returns (canonical_filename, bytes) or raises KeyError if not found."""
    data = open(fname, 'rb').read()
    pos = 0
    cnt = bread(data[pos:pos + 2]); pos += 2
    for _ in range(cnt):
        fn = sread(data[pos:pos + 12]); pos += 12
        pos += 4  # timestamp
        dataLen  = bread(data[pos:pos + 4]); pos += 4
        dataOffs = bread(data[pos:pos + 4]); pos += 4
        if fn.upper() == entry_name.upper():
            return fn, data[dataOffs:dataOffs + dataLen]
    raise KeyError(f"{entry_name!r} not found in {fname}")


def extractOne(fname, entry_name, ddir):
    """Extract a single named file from a CAT archive to ddir.
    Returns (out_path, size) or raises KeyError if entry_name not found."""
    data = open(fname, 'rb').read()
    pos = 0
    cnt = bread(data[pos:pos + 2]); pos += 2
    for _ in range(cnt):
        fn = sread(data[pos:pos + 12]); pos += 12
        pos += 4  # timestamp
        dataLen  = bread(data[pos:pos + 4]); pos += 4
        dataOffs = bread(data[pos:pos + 4]); pos += 4
        if fn.upper() == entry_name.upper():
            os.makedirs(ddir, exist_ok=True)
            out_path = os.path.join(ddir, fn)
            with open(out_path, 'wb') as fh:
                fh.write(data[dataOffs:dataOffs + dataLen])
            return out_path, dataLen
    raise KeyError(f"{entry_name!r} not found in {fname}")
