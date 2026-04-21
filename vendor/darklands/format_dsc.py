# Source: vvendigo/Darklands (MIT) — Python 3 fix: binary file reading
import os
import struct
from struct import unpack
from .utils import cstrim, encode_dl_bytes


def read_file(fname):
    data = open(fname, 'rb').read()  # Python 3 fix: binary mode
    data_len = len(data)
    pos = 0
    unknown, = unpack('B', data[pos:pos + 1]); pos += 1
    descs = []
    while pos < data_len:
        descs.append(cstrim(unpack('80s', data[pos:pos + 80])[0])); pos += 80
    return descs


def readData(dlPath):
    # Try both cases for cross-platform compatibility
    for name in ('DARKLAND.DSC', 'darkland.dsc'):
        path = os.path.join(dlPath, name)
        if os.path.exists(path):
            return read_file(path)
    return read_file(os.path.join(dlPath, 'DARKLAND.DSC'))  # let it raise


def write_file(fname, descs):
    count = len(descs)
    header_count = 0x5E if count == 92 else count
    data = bytearray(struct.pack('B', header_count & 0xFF))
    for desc in descs:
        raw = encode_dl_bytes(desc or "")[:79]
        data += raw.ljust(80, b'\x00')
    with open(fname, 'wb') as fh:
        fh.write(data)
