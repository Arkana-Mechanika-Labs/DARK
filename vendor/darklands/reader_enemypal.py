import os


def _vga6_to_8(value: int) -> int:
    return ((value & 0x3F) << 2) | ((value & 0x3F) >> 4)


def read_file(fname):
    data = open(fname, 'rb').read()
    chunk_size = 53
    palettes = []
    for idx in range(0, len(data) // chunk_size):
        raw = data[idx * chunk_size:(idx + 1) * chunk_size]
        if len(raw) < chunk_size:
            break
        start_offset = raw[0]
        colors = []
        pos = 1
        for _ in range(16):
            r = _vga6_to_8(raw[pos])
            g = _vga6_to_8(raw[pos + 1])
            b = _vga6_to_8(raw[pos + 2])
            colors.append((r, g, b))
            pos += 3
        start_index = start_offset // 3
        palettes.append({
            'index': idx,
            'start_offset': start_offset,
            'start_index': start_index,
            'block_index': start_index,
            'colors': colors,
            'unknown_tail': raw[49:53],
        })
    return palettes


def readData(dlPath):
    return read_file(os.path.join(dlPath, 'ENEMYPAL.DAT'))
