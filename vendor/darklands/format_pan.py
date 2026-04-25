from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WIDTH = 320
HEIGHT = 200
FRAMEBUFFER_SIZE = WIDTH * HEIGHT
PALETTE_SIZE = 256 * 3
MAGIC = 0x0A5A
RECORD_SIGNATURE = b"\x42\x00\x01\x00"

BUFFER_BASE = 0xA897
BUFFER_END = 0xB896
INITIAL_SI = BUFFER_BASE + 0x1000


class PanDecodeError(ValueError):
    pass


@dataclass(frozen=True)
class PanRecord:
    index: int
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class PanMetadata:
    frame_count: int
    compressed_size: int
    logical_size: int
    span_count: int
    table_end: int
    palette_offset: int
    first_record_offset: int


class _Runtime0070Decoder:
    """Clean-room port of Darklands' stateful 0DFC:0070 PAN stream decoder."""

    def __init__(self, raw: bytes):
        self.raw = bytes(raw)
        self.si = INITIAL_SI
        self.raw_offset = 0
        self.bp = 0
        self.dx = 0
        self.carry = False
        self.status = 0
        self.memory: dict[int, int] = {}
        self.span_count = 0

    def _rcr(self, value: int) -> int:
        old_carry = self.carry
        self.carry = bool(value & 0x0001)
        result = value >> 1
        if old_carry:
            result |= 0x8000
        return result & 0xFFFF

    def _rcl(self, value: int) -> int:
        old_carry = self.carry
        self.carry = bool(value & 0x8000)
        result = (value << 1) & 0xFFFF
        if old_carry:
            result |= 0x0001
        return result

    def _shr(self, value: int) -> int:
        self.carry = bool(value & 0x0001)
        return (value >> 1) & 0xFFFF

    def _refill(self) -> None:
        saved = self.memory.get(self.si, 0)
        self.si = (self.si - 0x1000) & 0xFFFF
        self.memory[self.si] = saved
        block = self.raw[self.raw_offset:self.raw_offset + 0x1000]
        self.raw_offset += len(block)
        for index, value in enumerate(block):
            self.memory[BUFFER_BASE + index] = value

    def _ensure_word(self) -> None:
        if self.si >= BUFFER_END:
            self._refill()

    def _ensure_byte(self) -> None:
        if self.si > BUFFER_END:
            self._refill()

    def _lodsb(self) -> int:
        value = self.memory.get(self.si, 0)
        self.si = (self.si + 1) & 0xFFFF
        return value

    def _lodsw(self) -> int:
        return self._lodsb() | (self._lodsb() << 8)

    def _initial_control_word(self) -> None:
        self._ensure_word()
        self.bp = self._lodsw()
        self.dx = 0x0010

    def _refresh_control_word(self) -> None:
        self._ensure_word()
        self.bp = self._shr(self.bp)
        word = self._lodsw()
        self.dx = 0x0010
        self.bp = self._rcl(word)

    def _next_control_bit(self) -> bool:
        self.dx = (self.dx - 1) & 0xFFFF
        if self.dx == 0:
            self._refresh_control_word()
        self.bp = self._rcr(self.bp)
        return self.carry

    def _copy_from_backref(self, out: bytearray, bx: int, count: int) -> None:
        signed_bx = bx - 0x10000 if bx & 0x8000 else bx
        for _ in range(count):
            source = len(out) + signed_bx
            out.append(out[source] if 0 <= source < len(out) else 0)

    def decode_span(self, out: bytearray) -> int:
        span_start = len(out)
        if self.dx == 0:
            self._initial_control_word()

        while True:
            if self._next_control_bit():
                self._ensure_byte()
                out.append(self._lodsb())
                continue

            cx = 0
            if self._next_control_bit():
                self._ensure_word()
                word = self._lodsw()
                bx = ((((word >> 8) >> 3) | 0xE0) << 8) | (word & 0x00FF)
                bx &= 0xFFFF
                count = (word >> 8) & 0x07
                if count:
                    cx = count + 2
                else:
                    self._ensure_byte()
                    value = self._lodsb()
                    if value <= 1:
                        self.status = value ^ 1
                        self.span_count += 1
                        return len(out) - span_start
                    cx = value + 1
                self._copy_from_backref(out, bx, cx)
                continue

            for _ in range(2):
                bit = self._next_control_bit()
                cx = ((cx << 1) | int(bit)) & 0xFFFF
                self.carry = False
            cx += 2
            self._ensure_byte()
            bx = 0xFF00 | self._lodsb()
            self._copy_from_backref(out, bx, cx)


def _u16(data: bytes | bytearray, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise PanDecodeError(f"truncated u16 at 0x{offset:05X}")
    return int.from_bytes(data[offset:offset + 2], "little")


def _logical_end_from_prefix(data: bytes | bytearray) -> int | None:
    if len(data) < 4:
        return None
    if _u16(data, 0) != MAGIC:
        return None
    count = _u16(data, 2)
    if count <= 0 or count > 4096:
        return None
    table_end = 4 + count * 2
    if len(data) < table_end:
        return None
    return sum(_u16(data, 4 + index * 2) for index in range(count))


def decode_logical_stream(raw: bytes, max_spans: int = 256) -> tuple[bytes, int]:
    decoder = _Runtime0070Decoder(raw)
    out = bytearray()
    logical_end: int | None = None

    for _ in range(max_spans):
        before = len(out)
        decoder.decode_span(out)
        logical_end = _logical_end_from_prefix(out)
        if logical_end is not None and len(out) >= logical_end:
            return bytes(out[:logical_end]), decoder.span_count
        if len(out) == before:
            break
        if decoder.status and logical_end is None:
            break

    if logical_end is not None and len(out) >= logical_end:
        return bytes(out[:logical_end]), decoder.span_count
    raise PanDecodeError("PAN stream ended before the logical frame table was complete")


def decode_vga_palette(raw_palette: bytes) -> list[tuple[int, int, int]]:
    if len(raw_palette) != PALETTE_SIZE:
        raise PanDecodeError(f"expected {PALETTE_SIZE} palette bytes, got {len(raw_palette)}")
    colors = []
    for offset in range(0, PALETTE_SIZE, 3):
        r6, g6, b6 = raw_palette[offset:offset + 3]
        colors.append((_vga6_to_rgb8(r6), _vga6_to_rgb8(g6), _vga6_to_rgb8(b6)))
    return colors


def _vga6_to_rgb8(value: int) -> int:
    value &= 0x3F
    return (value << 2) | (value >> 4)


def _fill(framebuffer: bytearray, offset: int, count: int, value: int) -> None:
    if count <= 0 or offset >= len(framebuffer):
        return
    end = min(len(framebuffer), offset + count)
    framebuffer[offset:end] = bytes([value]) * (end - offset)


def _literal(framebuffer: bytearray, offset: int, literal: bytes) -> None:
    if not literal or offset >= len(framebuffer):
        return
    end = min(len(framebuffer), offset + len(literal))
    framebuffer[offset:end] = literal[:end - offset]


def apply_frame_delta(payload: bytes, framebuffer: bytearray) -> dict[str, int | str]:
    cursor = 0
    dest = 0
    op_count = 0
    end_reason = "eof"

    while cursor < len(payload):
        op_count += 1
        opcode = payload[cursor]
        cursor += 1

        if opcode & 0x80:
            count = opcode - 0x80
            if count == 0:
                word = _u16(payload, cursor)
                cursor += 2
                if word == 0:
                    end_reason = "end16"
                    break
                if word & 0x8000:
                    if word & 0x4000:
                        count = word - 0xC000
                        if cursor >= len(payload):
                            end_reason = "truncated_fill16"
                            break
                        value = payload[cursor]
                        cursor += 1
                        _fill(framebuffer, dest, count, value)
                        dest += count
                    else:
                        count = word - 0x8000
                        if cursor + count > len(payload):
                            end_reason = "truncated_lit16"
                            break
                        _literal(framebuffer, dest, payload[cursor:cursor + count])
                        cursor += count
                        dest += count
                else:
                    dest += word
            else:
                dest += count
        elif opcode == 0:
            if cursor + 2 > len(payload):
                end_reason = "truncated_fill8"
                break
            count = payload[cursor]
            value = payload[cursor + 1]
            cursor += 2
            _fill(framebuffer, dest, count, value)
            dest += count
        else:
            count = opcode
            if cursor + count > len(payload):
                end_reason = "truncated_lit8"
                break
            _literal(framebuffer, dest, payload[cursor:cursor + count])
            cursor += count
            dest += count

    return {"consumed": cursor, "end_reason": end_reason, "op_count": op_count, "dest": dest}


class PanSequence:
    def __init__(self, raw: bytes, logical: bytes, span_count: int, source_name: str = ""):
        self.raw = bytes(raw)
        self.logical = bytes(logical)
        self.span_count = span_count
        self.source_name = source_name
        self.frame_count = _u16(self.logical, 2)
        self.table_end = 4 + self.frame_count * 2
        self.palette_offset = self.table_end
        self.palette_end = self.palette_offset + PALETTE_SIZE
        self.first_record_offset = self.palette_end
        self.deltas = [_u16(self.logical, 4 + index * 2) for index in range(self.frame_count)]
        self.palette_raw = self.logical[self.palette_offset:self.palette_end]
        self.palette = decode_vga_palette(self.palette_raw)
        self.records = self._build_records()
        self.metadata = PanMetadata(
            frame_count=self.frame_count,
            compressed_size=len(self.raw),
            logical_size=len(self.logical),
            span_count=self.span_count,
            table_end=self.table_end,
            palette_offset=self.palette_offset,
            first_record_offset=self.first_record_offset,
        )

    @classmethod
    def from_bytes(cls, raw: bytes, source_name: str = "") -> "PanSequence":
        logical, span_count = decode_logical_stream(raw)
        if _u16(logical, 0) != MAGIC:
            raise PanDecodeError("not a PAN logical stream: missing 0x0A5A magic")
        return cls(raw, logical, span_count, source_name)

    @classmethod
    def from_file(cls, path: str | Path) -> "PanSequence":
        path = Path(path)
        return cls.from_bytes(path.read_bytes(), path.name)

    def _build_records(self) -> list[PanRecord]:
        if self.palette_end > len(self.logical):
            raise PanDecodeError("PAN palette extends past logical stream")
        records = []
        start = self.first_record_offset
        end = 0
        for index, delta in enumerate(self.deltas):
            end += delta
            if end > len(self.logical):
                raise PanDecodeError(f"record {index} extends past logical stream")
            if self.logical[start:start + 4] != RECORD_SIGNATURE:
                raise PanDecodeError(f"record {index} missing 42/1 signature at 0x{start:05X}")
            records.append(PanRecord(index, start, end))
            start = end
        return records

    def replay_framebuffers(self) -> list[bytes]:
        return list(self.iter_framebuffers())

    def iter_framebuffers(self):
        framebuffer = bytearray(FRAMEBUFFER_SIZE)
        for record in self.records:
            self.apply_record(record.index, framebuffer)
            yield bytes(framebuffer)

    def apply_record(self, index: int, framebuffer: bytearray) -> dict[str, int | str]:
        record = self.records[index]
        payload = self.logical[record.start + len(RECORD_SIGNATURE):record.end]
        return apply_frame_delta(payload, framebuffer)

    def rgba_frame(self, framebuffer: bytes | bytearray) -> bytes:
        if len(framebuffer) != FRAMEBUFFER_SIZE:
            raise PanDecodeError(f"expected {FRAMEBUFFER_SIZE} framebuffer bytes")
        buf = bytearray(FRAMEBUFFER_SIZE * 4)
        for index, color_index in enumerate(framebuffer):
            r, g, b = self.palette[color_index]
            out = index * 4
            buf[out] = b
            buf[out + 1] = g
            buf[out + 2] = r
            buf[out + 3] = 255
        return bytes(buf)

    def frame_rgba_sequence(self) -> list[bytes]:
        return list(self.iter_rgba_frames())

    def iter_rgba_frames(self):
        for framebuffer in self.iter_framebuffers():
            yield self.rgba_frame(framebuffer)
