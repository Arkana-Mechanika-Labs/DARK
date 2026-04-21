# Darklands MAP file writer - mirrors reader_map.py in reverse.
# RLE byte layout: (run_len << 5) | (pal << 4) | tile_row
# Header uses big-endian uint16 (rbread in reader); row offsets use little-endian uint32.
import struct


def _rle_encode_row(row):
    """
    RLE-encode one map row.

    row: list of (pal, tile_row) or (pal, tile_row, col)
         col is ignored - it is recomputed by reader_map on next load.
    Returns: bytes
    """
    result = bytearray()
    n = len(row)
    i = 0
    while i < n:
        pal, r = row[i][0], row[i][1]
        run = 1
        # max run length = 7  (3 bits: values 1-7; 0 would mean no-op)
        while run < 7 and i + run < n and row[i + run][0] == pal and row[i + run][1] == r:
            run += 1
        result.append((run << 5) | (pal << 4) | r)
        i += run
    return bytes(result)


def writeData(path, m):
    """
    Write 2-D tile grid *m* to a Darklands .MAP file at *path*.

    m[y][x] must be (pal, tile_row) or (pal, tile_row, col).
    The col adjacency field is NOT stored (it is recomputed by reader_map.readData
    when the file is next loaded).

    File format:
        uint16 BE  max_x_size
        uint16 BE  max_y_size
        uint32 LE x max_y_size  row_offsets   (absolute byte positions)
        <row data - RLE packed>
    """
    max_y = len(m)
    max_x = len(m[0]) if m else 0

    encoded_rows = [_rle_encode_row(row) for row in m]
    header_size = 4 + max_y * 4

    offsets = []
    pos = header_size
    for row_bytes in encoded_rows:
        offsets.append(pos)
        pos += len(row_bytes)

    with open(path, 'wb') as f:
        f.write(struct.pack('>HH', max_x, max_y))
        for off in offsets:
            f.write(struct.pack('<I', off))
        for row_bytes in encoded_rows:
            f.write(row_bytes)
