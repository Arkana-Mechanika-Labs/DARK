from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import fnmatch
import re


STATUS_LABELS = {
    "editable": "Editable",
    "supported": "Supported",
    "wip": "WIP",
    "runtime": "Runtime",
    "unknown": "Unknown",
}


@dataclass(frozen=True)
class CoverageRule:
    key: str
    patterns: tuple[str, ...]
    status: str
    category: str
    family: str
    editor_title: str | None = None
    kb_doc: str | None = None
    notes: str = ""
    match_kind: str = "file"


@dataclass(frozen=True)
class CoverageEntry:
    name: str
    path: str
    is_dir: bool
    status: str
    category: str
    family: str
    editor_title: str | None
    kb_doc: str | None
    notes: str
    rule_key: str

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status.capitalize())


@dataclass(frozen=True)
class CoverageReport:
    root_path: str
    entries: list[CoverageEntry]

    @property
    def counts(self) -> Counter:
        return Counter(entry.status for entry in self.entries)


_RULES: tuple[CoverageRule, ...] = (
    CoverageRule(
        key="saves_dir",
        patterns=("SAVES",),
        status="editable",
        category="folder",
        family="Save-game folder",
        editor_title="Save Game Editor",
        kb_doc="20_File_Formats/By_Type/Save Formats.md",
        notes="Contains DKSAVE??.SAV files editable through the save-game editor.",
        match_kind="dir",
    ),
    CoverageRule(
        key="pics_dir",
        patterns=("PICS",),
        status="editable",
        category="folder",
        family="PIC image folder",
        editor_title="PIC Images",
        kb_doc="20_File_Formats/By_Type/Graphics/pic_files.md",
        notes="Primary loose PIC asset directory.",
        match_kind="dir",
    ),
    CoverageRule(
        key="darkland_cty",
        patterns=("DARKLAND.CTY",),
        status="editable",
        category="world",
        family="City data",
        editor_title="Cities",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.cty.md",
        notes="Structured city records and linked location names.",
    ),
    CoverageRule(
        key="darkland_dsc",
        patterns=("DARKLAND.DSC",),
        status="editable",
        category="world",
        family="City descriptions",
        editor_title="Descriptions (DSC)",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.dsc.md",
        notes="Description strings associated with cities.",
    ),
    CoverageRule(
        key="darkland_enm",
        patterns=("DARKLAND.ENM",),
        status="editable",
        category="world",
        family="Enemy data",
        editor_title="Enemies",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.enm.md",
        notes="Enemy types and encounter data.",
    ),
    CoverageRule(
        key="darkland_loc",
        patterns=("DARKLAND.LOC", "LOCS.TMP"),
        status="editable",
        category="world",
        family="World locations",
        editor_title="Locations",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.loc.md",
        notes="World-map location records; LOCS.TMP mirrors the main data in saves/runtime workflows.",
    ),
    CoverageRule(
        key="darkland_lst",
        patterns=("DARKLAND.LST",),
        status="editable",
        category="world",
        family="Items / Formulae",
        editor_title="Items, Saints & Formulae",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.lst.md",
        notes="Item definitions and related formula data.",
    ),
    CoverageRule(
        key="darkland_snt",
        patterns=("DARKLAND.SNT",),
        status="editable",
        category="world",
        family="Saint data",
        editor_title="Items, Saints & Formulae",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.snt.md",
        notes="Saint records and descriptions used by the shared items/saints/formulae editor.",
    ),
    CoverageRule(
        key="darkland_map",
        patterns=("DARKLAND.MAP",),
        status="editable",
        category="world",
        family="World map",
        editor_title="World Map",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.map.md",
        notes="Interactive world map viewer/editor already exists in the app.",
    ),
    CoverageRule(
        key="darkland_msg",
        patterns=("DARKLAND.MSG",),
        status="editable",
        category="text",
        family="Dialog cards",
        editor_title="Dialog Cards (MSG)",
        kb_doc="20_File_Formats/By_Type/Graphics/msg_files.md",
        notes="Loose MSG file editable in the dialog-card editor.",
    ),
    CoverageRule(
        key="msgfiles_archive",
        patterns=("MSGFILES",),
        status="editable",
        category="archive",
        family="Dialog-card archive",
        editor_title="Dialog Cards (MSG)",
        kb_doc="20_File_Formats/By_Type/Graphics/msg_files.md",
        notes="Most in-game MSG files live in this catalog-style container.",
    ),
    CoverageRule(
        key="pic_entries",
        patterns=("*.PIC",),
        status="editable",
        category="graphics",
        family="PIC image",
        editor_title="PIC Images",
        kb_doc="20_File_Formats/By_Type/Graphics/pic_files.md",
        notes="Loose PIC image or CAT entry supported by the PIC tool.",
    ),
    CoverageRule(
        key="imc_entries",
        patterns=("*.IMC",),
        status="editable",
        category="graphics",
        family="IMC sprite",
        editor_title="IMC Sprites",
        kb_doc="20_File_Formats/By_Type/Graphics/imc_files.md",
        notes="Tactical sprite entry supported by the IMC tool.",
    ),
    CoverageRule(
        key="msg_entries",
        patterns=("*.MSG",),
        status="editable",
        category="text",
        family="MSG dialog file",
        editor_title="Dialog Cards (MSG)",
        kb_doc="20_File_Formats/By_Type/Graphics/msg_files.md",
        notes="Dialog-card file supported by the MSG editor.",
    ),
    CoverageRule(
        key="pic_catalogs",
        patterns=("*.CAT", "BC", "LCASTLE"),
        status="editable",
        category="archive",
        family="Catalog archive",
        editor_title="CAT Extractor",
        kb_doc="20_File_Formats/By_Type/Catalog Formats.md",
        notes="Editable through the archive browser; known inner types get richer previews.",
    ),
    CoverageRule(
        key="fonts",
        patterns=("FONTS.FNT", "FONTS.UTL"),
        status="editable",
        category="graphics",
        family="Font set",
        editor_title="Font Viewer (FNT/UTL)",
        kb_doc="20_File_Formats/By_Type/Graphics/font_sets.md",
        notes="Bitmap font sets with editing support.",
    ),
    CoverageRule(
        key="enemypal",
        patterns=("ENEMYPAL.DAT",),
        status="supported",
        category="graphics",
        family="Enemy palettes",
        editor_title=None,
        kb_doc="20_File_Formats/By_Type/Graphics/enemypal.dat.md",
        notes="Understood and used by ENM/IMC/CAT previews, but not yet a standalone editor.",
    ),
    CoverageRule(
        key="level0_enm",
        patterns=("LEVEL0.ENM",),
        status="supported",
        category="world",
        family="Auxiliary ENM-related data",
        editor_title="Research Files",
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.enm.md",
        notes="Mentioned alongside DARKLAND.ENM in the KB, but much smaller and not the same layout; treat as a research/support file for now.",
    ),
    CoverageRule(
        key="alc",
        patterns=("DARKLAND.ALC",),
        status="supported",
        category="world",
        family="Alchemy data",
        editor_title=None,
        kb_doc="20_File_Formats/By_Type/World_Data/darkland.alc.md",
        notes="Known format with KB coverage, but not yet surfaced as a dedicated editor.",
    ),
    CoverageRule(
        key="img_files",
        patterns=("*.IMG",),
        status="wip",
        category="graphics",
        family="IMG banks",
        editor_title="IMG Banks (WIP)",
        kb_doc="WIP/COMMONSP/COMMONSP_IMG.md",
        notes="Research has progressed, especially for COMMONSP.IMG; not yet integrated as an editor.",
    ),
    CoverageRule(
        key="pan_files",
        patterns=("*.PAN",),
        status="wip",
        category="presentation",
        family="PAN sequences",
        editor_title="PAN Sequences (WIP)",
        kb_doc="WIP/PAN/PAN_Format.md",
        notes="Actively researched presentation/script format; not yet integrated in the browser.",
    ),
    CoverageRule(
        key="tmp_runtime",
        patterns=("*.TMP", "CACHE.TMP", "*.BAK"),
        status="runtime",
        category="runtime",
        family="Runtime temp data",
        editor_title=None,
        kb_doc=None,
        notes="Runtime or cache data; usually not a primary editing target.",
    ),
    CoverageRule(
        key="sound_assets",
        patterns=("*.DB", "*.DC", "*.DLB", "*.DLC"),
        status="unknown",
        category="audio",
        family="Audio assets",
        editor_title=None,
        kb_doc=None,
        notes="Out of the current browser scope.",
    ),
    CoverageRule(
        key="dgt_audio",
        patterns=("*.DGT",),
        status="supported",
        category="audio",
        family="DGT presentation audio",
        editor_title="DGT Audio",
        kb_doc="20_File_Formats/By_Type/Audio/dgt_files.md",
        notes="Raw unsigned 8-bit mono PCM presentation audio; playable and exportable as WAV in DARK.",
    ),
    CoverageRule(
        key="executables",
        patterns=("*.EXE", "*.COM", "*.BAT"),
        status="unknown",
        category="binary",
        family="Executable/runtime binary",
        editor_title=None,
        kb_doc=None,
        notes="Executable or helper binary, not an editor target.",
    ),
    CoverageRule(
        key="misc_runtime_dirs",
        patterns=("CONVERT", "QCAP", "FILE_FORMATS", "LOGS"),
        status="runtime",
        category="folder",
        family="Support folder",
        editor_title=None,
        kb_doc=None,
        notes="Support, capture, or documentation folder rather than core game content.",
        match_kind="dir",
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_kb_root() -> str | None:
    config_path = _repo_root() / "paths.local.md"
    if not config_path.exists():
        return None
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"\{DARKLANDS_KB\}:\s*`([^`]+)`", text)
    if not match:
        return None
    return match.group(1)


def resolve_kb_doc(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    kb_root = resolve_kb_root()
    if not kb_root:
        return None
    return str(Path(kb_root) / relative_path)


def _matches(rule: CoverageRule, name: str, is_dir: bool) -> bool:
    if rule.match_kind == "dir" and not is_dir:
        return False
    if rule.match_kind == "file" and is_dir:
        return False
    upper_name = name.upper()
    return any(fnmatch.fnmatch(upper_name, pattern.upper()) for pattern in rule.patterns)


def classify_path(path: str) -> CoverageEntry:
    item = Path(path)
    name = item.name
    is_dir = item.is_dir()
    return classify_name(name, path=str(item), is_dir=is_dir)


def classify_name(name: str, path: str | None = None, is_dir: bool = False) -> CoverageEntry:
    for rule in _RULES:
        if _matches(rule, name, is_dir):
            return CoverageEntry(
                name=name,
                path=path or name,
                is_dir=is_dir,
                status=rule.status,
                category=rule.category,
                family=rule.family,
                editor_title=rule.editor_title,
                kb_doc=resolve_kb_doc(rule.kb_doc),
                notes=rule.notes,
                rule_key=rule.key,
            )
    return CoverageEntry(
        name=name,
        path=path or name,
        is_dir=is_dir,
        status="unknown",
        category="folder" if is_dir else "file",
        family="Unclassified",
        editor_title=None,
        kb_doc=None,
        notes="No explicit coverage rule yet.",
        rule_key="unknown",
    )


def scan_directory(root_path: str) -> CoverageReport:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return CoverageReport(root_path=root_path, entries=[])
    children = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.upper()))
    entries = [classify_path(str(child)) for child in children]
    return CoverageReport(root_path=str(root), entries=entries)
