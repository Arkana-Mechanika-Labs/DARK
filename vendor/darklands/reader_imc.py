from .reader_drle import readData as drle_read


def decode_frame(frame_data):
    if not frame_data or len(frame_data) < 2:
        return []
    width = frame_data[0]
    height = frame_data[1]
    pos = 2
    rows = []
    for _ in range(height):
        if pos + 2 > len(frame_data):
            break
        defined = frame_data[pos]
        pos += 1
        empty = frame_data[pos]
        pos += 1
        row = [0] * empty
        chunk = list(frame_data[pos:pos + defined])
        pos += defined
        row.extend(chunk)
        if len(row) < width:
            row.extend([0] * (width - len(row)))
        rows.append(row[:width])
    while len(rows) < height:
        rows.append([0] * width)
    return rows


def encode_frame(rows):
    height = len(rows)
    width = max((len(row) for row in rows), default=0)
    if width > 255 or height > 255:
        raise ValueError("IMC frames support at most 255x255 pixels")
    out = bytearray([width, height])
    for row in rows:
        row_data = list(row[:width]) + [0] * max(0, width - len(row))
        nz = [idx for idx, value in enumerate(row_data) if value]
        if not nz:
            out.extend((0, width))
            continue
        start = nz[0]
        end = nz[-1]
        chunk = row_data[start:end + 1]
        if len(chunk) > 255 or start > 255:
            raise ValueError("IMC row run exceeds byte-sized limits")
        out.extend((len(chunk), start))
        out.extend(max(0, min(255, int(value))) for value in chunk)
    return bytes(out)


def _drle_literal_compress(data):
    data = bytes(data)
    out = bytearray()

    def emit_word(word: int):
        out.extend(int(word & 0xFFFF).to_bytes(2, "little"))

    if not data:
        emit_word(0x0000)
        out.extend(b"\x00\x00\x00")
        return bytes(out)

    pos = 0
    if len(data) <= 15:
        emit_word((1 << len(data)) - 1)
        out.extend(data)
        out.extend(b"\x00\x00\x00")
        return bytes(out)

    emit_word(0xFFFF)
    out.extend(data[:15])
    pos = 15
    out_len = 15

    while True:
        remaining = len(data) - pos
        if out_len < 256:
            if remaining <= 16:
                emit_word((1 << (remaining - 1)) - 1)
                out.extend(data[pos:pos + remaining])
                out.extend(b"\x00\x00\x00")
                return bytes(out)
        else:
            if remaining <= 15:
                emit_word((1 << remaining) | ((1 << (remaining - 1)) - 1))
                out.extend(data[pos:pos + remaining])
                out.extend(b"\x00\x00\x00")
                return bytes(out)
            if remaining == 16:
                emit_word(0x7FFF)
                out.extend(data[pos:pos + 16])
                emit_word(0x0001)
                out.extend(b"\x00\x00\x00")
                return bytes(out)

        emit_word(0xFFFF)
        out.extend(data[pos:pos + 16])
        pos += 16
        out_len += 16
    return bytes(out)


def writeDataBytes(imc, name=""):
    raw_template = bytes(imc.get("raw", b""))
    if not raw_template:
        raise ValueError("IMC object is missing raw template data")
    dy_file = "DY" in name.upper()
    size_off = 0x3E if dy_file else 0x52
    if len(raw_template) < size_off + 2:
        raise ValueError("IMC raw template is too short")

    frame_defs = imc.get("frames", [])
    offsets = []
    image_blob = bytearray()
    block_off = 0
    for frame in frame_defs:
        rows = frame.get("rows", [])
        frame_bytes = encode_frame(rows)
        frame["data"] = frame_bytes
        offsets.append(block_off)
        image_blob.extend(frame_bytes)
        padding = (-len(frame_bytes)) % 16
        if padding:
            image_blob.extend(b"\x00" * padding)
        block_off += (len(frame_bytes) + padding) // 16

    rebuilt = bytearray(raw_template[:size_off])
    rebuilt.extend(len(image_blob).to_bytes(2, "little"))
    for off in offsets:
        rebuilt.extend(int(off).to_bytes(2, "little"))
    rebuilt.extend(image_blob)
    imc["raw"] = bytes(rebuilt)
    return _drle_literal_compress(imc["raw"])


def readDataBytes(raw, name=""):
    data = bytes(drle_read(raw))
    if not data:
        return {"frames": [], "raw": data}
    dy_file = "DY" in name.upper()
    size_off = 0x3E if dy_file else 0x52
    if len(data) < size_off + 2:
        return {"frames": [], "raw": data}
    img_data_size = int.from_bytes(data[size_off:size_off + 2], "little")
    img_data_start = len(data) - img_data_size
    pos = size_off + 2
    offsets = []
    while pos + 1 < img_data_start and len(offsets) <= 200:
        offsets.append(int.from_bytes(data[pos:pos + 2], "little"))
        pos += 2
    offsets.sort()
    frames = []
    if offsets:
        for i, off in enumerate(offsets):
            start = img_data_start + 16 * off
            if i + 1 < len(offsets):
                end = img_data_start + 16 * offsets[i + 1]
            else:
                end = len(data)
            frame_bytes = data[start:end]
            frames.append({
                "offset": start,
                "data": frame_bytes,
                "rows": decode_frame(frame_bytes),
            })
    return {"frames": frames, "raw": data}


def render_rgba(rows, palette):
    height = len(rows)
    width = max((len(row) for row in rows), default=0)
    buf = bytearray(width * height * 4)
    for y, row in enumerate(rows):
        for x, ci in enumerate(row):
            if ci == 0:
                continue
            color = None
            if 0 <= ci < len(palette):
                color = palette[ci]
            if color is None:
                continue
            off = (y * width + x) * 4
            buf[off] = color[2]
            buf[off + 1] = color[1]
            buf[off + 2] = color[0]
            buf[off + 3] = 255
    return bytes(buf), width, height
