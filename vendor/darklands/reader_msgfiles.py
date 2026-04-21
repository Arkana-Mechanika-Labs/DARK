import os
import struct
from dataclasses import dataclass


CATALOG_HEADER_SIZE = 2
CATALOG_ENTRY_SIZE = 24
FILENAME_FIELD_SIZE = 12


@dataclass(frozen=True)
class MsgFilesEntry:
    index: int
    filename: str
    raw_field_0c: int
    size: int
    offset: int


class MsgFilesArchive:
    def __init__(self, path: str, entries: list[MsgFilesEntry]):
        self.path = path
        self.entries = entries
        self._by_name = {entry.filename.upper(): entry for entry in entries}

    @classmethod
    def open(cls, path: str) -> "MsgFilesArchive":
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        with open(path, "rb") as fh:
            header = fh.read(CATALOG_HEADER_SIZE)
            if len(header) != CATALOG_HEADER_SIZE:
                raise ValueError("MSGFILES is too small to contain a header.")
            (count,) = struct.unpack("<H", header)
            raw_catalog = fh.read(count * CATALOG_ENTRY_SIZE)
            if len(raw_catalog) != count * CATALOG_ENTRY_SIZE:
                raise ValueError("MSGFILES catalog is truncated.")

        entries = []
        for idx in range(count):
            base = idx * CATALOG_ENTRY_SIZE
            record = raw_catalog[base:base + CATALOG_ENTRY_SIZE]
            filename = _read_cstring(record[0:FILENAME_FIELD_SIZE])
            raw_field_0c = struct.unpack("<I", record[0x0C:0x10])[0]
            size = struct.unpack("<I", record[0x10:0x14])[0]
            offset = struct.unpack("<I", record[0x14:0x18])[0]
            entries.append(MsgFilesEntry(idx, filename, raw_field_0c, size, offset))
        return cls(path, entries)

    @property
    def first_payload_offset(self) -> int:
        if not self.entries:
            return CATALOG_HEADER_SIZE
        return self.entries[0].offset

    def get(self, filename: str) -> MsgFilesEntry | None:
        return self._by_name.get(str(filename).upper())

    def validate(self) -> list[str]:
        issues = []
        if not self.entries:
            return ["empty catalog"]
        expected_start = CATALOG_HEADER_SIZE + len(self.entries) * CATALOG_ENTRY_SIZE
        if self.entries[0].offset != expected_start:
            issues.append(
                f"first entry offset {self.entries[0].offset} != expected catalog end {expected_start}"
            )
        for prev, cur in zip(self.entries, self.entries[1:]):
            expected = prev.offset + prev.size
            if cur.offset != expected:
                issues.append(
                    f"{cur.filename}: expected offset {expected}, got {cur.offset}"
                )
        return issues


def _read_cstring(raw: bytes) -> str:
    end = raw.find(b"\x00")
    if end == -1:
        end = len(raw)
    return raw[:end].decode("latin-1", errors="replace")


def readData(path: str) -> MsgFilesArchive:
    return MsgFilesArchive.open(path)
