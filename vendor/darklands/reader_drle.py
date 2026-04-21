# Source: vvendigo/Darklands (MIT) - updated to the more accurate carry-based
# decoder model used in our local reversing scripts. This version matches the
# original game files and also accepts the literal-only streams we generate
# when rebuilding IMC data.
import struct

class _DrleDecompressor:
    def __init__(self):
        self.carry = False

    def _rc_right(self, value: int) -> int:
        old_carry = self.carry
        self.carry = bool(value & 0x0001)
        result = value >> 1
        if old_carry:
            result |= 0x8000
        return result & 0xFFFF

    def _rc_left(self, value: int) -> int:
        old_carry = self.carry
        self.carry = bool(value & 0x8000)
        result = (value << 1) & 0xFFFF
        if old_carry:
            result |= 0x0001
        return result

    def _sc_right(self, value: int) -> int:
        self.carry = bool(value & 0x0001)
        return (value >> 1) & 0xFFFF

    def _refresh_ctrl(self, data: bytes, offset: int, ctrl: int) -> tuple[int, int]:
        ctrl = self._sc_right(ctrl)
        if offset + 2 > len(data):
            return ctrl, len(data)
        ctrl = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        ctrl = self._rc_left(ctrl)
        return ctrl, offset

    def decompress(self, data: bytes) -> bytes:
        if len(data) < 2:
            return b""

        out = bytearray()
        ctrl = struct.unpack_from("<H", data, 0)[0]
        offset = 2
        dx = 16

        while offset < len(data):
            dx -= 1
            if dx == 0:
                dx = 16
                ctrl, offset = self._refresh_ctrl(data, offset, ctrl)
                if offset >= len(data):
                    break

            ctrl = self._rc_right(ctrl)
            if self.carry:
                out.append(data[offset])
                offset += 1
                continue

            counter = 0
            dx -= 1
            if dx == 0:
                dx = 16
                ctrl, offset = self._refresh_ctrl(data, offset, ctrl)
                if offset >= len(data):
                    break

            ctrl = self._rc_right(ctrl)
            if self.carry:
                if offset + 2 > len(data):
                    break
                raw_offset = struct.unpack_from("<H", data, offset)[0]
                offset += 2

                counter = (raw_offset & 0x0700) >> 8
                upper = ((raw_offset >> 3) & 0xFF00) | 0xE000
                lower = raw_offset & 0x00FF
                back_offset = (upper + lower) & 0xFFFF

                if counter == 0:
                    if offset >= len(data):
                        break
                    value = data[offset]
                    offset += 1
                    if value <= 1:
                        break
                    counter = value + 1
                else:
                    counter += 2
            else:
                for _ in range(2):
                    dx -= 1
                    if dx == 0:
                        dx = 16
                        ctrl, offset = self._refresh_ctrl(data, offset, ctrl)
                        if offset >= len(data):
                            break
                    ctrl = self._rc_right(ctrl)
                    counter = (counter << 1) + int(self.carry)
                    self.carry = False

                counter += 2
                if offset >= len(data):
                    break
                back_offset = 0xFF00 + data[offset]
                offset += 1

            back_offset = 0xFFFF - back_offset
            for _ in range(counter):
                if back_offset < len(out):
                    out.append(out[len(out) - back_offset - 1])

        return bytes(out)


def readData(data):
    """Decompress DRLE data. data can be bytes or list-of-ints."""
    return list(_DrleDecompressor().decompress(bytes(data)))


def readFile(fname):
    """Read and decompress a DRLE-compressed file. Returns list of ints (bytes)."""
    return readData(open(fname, 'rb').read())


def extractToFile(inPath, outPath):
    """Decompress inPath and write result to outPath."""
    data = readData(open(inPath, 'rb').read())
    with open(outPath, 'wb') as fh:
        fh.write(bytes(data))
