"""
Data converters: enemies, locations, items/saints/formulae, world map, cities.
All use the DL data directory path and auto-load when first shown / path changes.
"""
import io
import os
import re
import struct
import traceback
import copy
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QWidget, QVBoxLayout, QSplitter,
    QListWidget, QTreeWidget, QTreeWidgetItem, QScrollArea, QFormLayout,
    QGroupBox, QLineEdit, QSpinBox, QPushButton, QFrame, QMessageBox,
    QSizePolicy, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QImage, QPixmap, QColor, QBrush

from .base import TextConverter, ImageConverter
from app.file_ops import backup_existing_file, backup_label
from app.validation import filter_issues, summarize_issues, validate_world_data


_EDITED_STYLE = "background-color: rgba(215, 170, 47, 0.18);"


def _set_widget_edited(widget, edited: bool):
    base = widget.property("_base_style")
    if base is None:
        base = widget.styleSheet()
        widget.setProperty("_base_style", base)
    widget.setStyleSheet(f"{base}\n{_EDITED_STYLE}" if edited else base)


def _confirm_validation(parent, dl_path: str, scopes: tuple[str, ...], overrides: dict, title: str) -> bool:
    report = validate_world_data(dl_path, overrides)
    issues = filter_issues(report, scopes)
    if not issues:
        return True
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText("Validation found related issues.")
    box.setInformativeText("Save anyway?")
    box.setDetailedText(summarize_issues(issues, max_lines=12))
    save_btn = box.addButton("Save Anyway", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is save_btn


# ---------------------------------------------------------------------------
# Enemies — editable form UI
# ---------------------------------------------------------------------------

_ATTR_KEYS   = ('end', 'str', 'agl', 'per', 'int', 'chr', 'df')
_SKILL_KEYS  = ('wEdg', 'wImp', 'wFll', 'wPol', 'wThr', 'wBow', 'wMsl',
                'alch', 'relg', 'virt', 'spkC', 'spkL', 'r_w', 'heal',
                'artf', 'stlh', 'strW', 'ride', 'wdWs')

_ATTR_LABELS = {
    'end': 'Endurance', 'str': 'Strength',  'agl': 'Agility',
    'per': 'Perception','int': 'Intelligence','chr': 'Charisma', 'df': 'Defense',
}
_SKILL_LABELS = {
    'wEdg': 'Edge Weapons',   'wImp': 'Impact Weapons', 'wFll': 'Flail & Chain',
    'wPol': 'Polearms',       'wThr': 'Thrown',
    'wBow': 'Bow',            'wMsl': 'Crossbow',
    'alch': 'Alchemy',        'relg': 'Religion',       'virt': 'Virtue',
    'spkC': 'Speak Common',   'spkL': 'Speak Latin',    'r_w':  'Read/Write',
    'heal': 'Healing',        'artf': 'Artifice',
    'stlh': 'Stealth',        'strW': 'Streetwise',
    'ride': 'Riding',         'wdWs': 'Woodswise',
}
_ETYPE_SIZE  = 204   # bytes per enemy-type record
_EINST_SIZE  = 24    # bytes per enemy-instance record
_ETYPE_COUNT = 71
_EINST_COUNT = 82


# ── Binary encode helpers ────────────────────────────────────────────────────

def _encode_enemy_type(et: dict) -> bytes:
    """Reconstruct 204-byte enemy-type binary record from dict."""
    buf = bytearray(_ETYPE_SIZE)
    # image_group  (4 bytes, null-padded ASCII)
    ig = et['image_group'].encode('ascii', errors='replace')[:4]
    buf[0:len(ig)] = ig
    # name (10 bytes, null-padded)
    name = et['name'].encode('ascii', errors='replace')[:9]
    buf[4:4 + len(name)] = name
    buf[14] = et['num_variants'] & 0xFF
    buf[15] = et['pal_cnt']      & 0xFF
    buf[16] = et['unknown2']     & 0xFF
    buf[17] = et['pal_start']    & 0xFF
    # unknown4 — stored as int or raw bytes
    unk4 = et['unknown4']
    if isinstance(unk4, int):
        struct.pack_into('<H', buf, 18, unk4 & 0xFFFF)
    else:
        buf[18:20] = bytes(unk4)[:2]
    # attrs (7 bytes @ 20)
    for j, k in enumerate(_ATTR_KEYS):
        buf[20 + j] = et['attrs'][k] & 0xFF
    # skills (19 bytes @ 27)
    for j, k in enumerate(_SKILL_KEYS):
        buf[27 + j] = et['skills'][k] & 0xFF
    buf[46] = et['unknown5'] & 0xFF
    buf[47] = 0               # const 0
    buf[48] = et['unknown6'] & 0xFF
    buf[49] = et['unknown7'] & 0xFF
    # unknown8 (66 bytes @ 50)
    unk8 = bytes(et['unknown8'])[:0x42]
    buf[50:50 + len(unk8)] = unk8
    # unknown9 (30 bytes @ 116)
    unk9 = bytes(et['unknown9'])[:0x1e]
    buf[116:116 + len(unk9)] = unk9
    # unknown10 (2 bytes @ 146)
    unk10 = bytes(et['unknown10'])[:2]
    buf[146:146 + len(unk10)] = unk10
    buf[148] = et['vital_arm_type']    & 0xFF
    buf[149] = et['limb_arm_typetype'] & 0xFF
    buf[150] = et['armor_q']           & 0xFF
    buf[151] = et['unknown11']         & 0xFF
    buf[152] = et['shield_type']       & 0xFF
    buf[153] = et['shield_q']          & 0xFF
    unk12 = bytes(et['unknown12'])[:6]
    buf[154:154 + len(unk12)] = unk12
    unk13 = bytes(et['unknown13'])[:6]
    buf[160:160 + len(unk13)] = unk13
    wt = bytes(et['weapon_types'])[:6]
    buf[166:166 + len(wt)] = wt
    buf[172] = et['weapon_q'] & 0xFF
    unk14 = bytes(et['unknown14'])[:11]
    buf[173:173 + len(unk14)] = unk14
    unk15 = bytes(et['unknown15'])[:20]
    buf[184:184 + len(unk15)] = unk15
    return bytes(buf)


def _encode_enemy_instance(e: dict) -> bytes:
    """Reconstruct 24-byte enemy-instance binary record from dict."""
    buf = bytearray(_EINST_SIZE)
    struct.pack_into('<H', buf, 0, e['type'] & 0xFFFF)
    name = e['name'].encode('ascii', errors='replace')[:11]
    buf[2:2 + len(name)] = name
    # 8 zero bytes at 14 (already zero)
    struct.pack_into('<H', buf, 22, e['unknown'] & 0xFFFF)
    return bytes(buf)


# ── Editable UI ──────────────────────────────────────────────────────────────

class EnemiesConverter(QWidget):
    """
    Enemy editor for DARKLAND.ENM.

    Left panel (vertical splitter):
      • Enemy Types list  — 71 template definitions
      • Named Encounters list — 82 named groups that reference a type

    Right panel:
      • Selecting a type    → shows the type form only; highlights matching encounters
      • Selecting encounter → shows a compact encounter card above the same type form
    """

    _auto_on_path = True
    _PV_W, _PV_H = 256, 192

    # Brushes for encounter cross-highlighting
    _BRUSH_MATCH   = QBrush(QColor('#1a5fa3'))   # encounters that use the selected type
    _BRUSH_DIM     = QBrush(QColor('#b0b0b0'))   # encounters that do not
    _BRUSH_DEFAULT = QBrush()                    # restore system default

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path        = ""
        self._needs_refresh = True
        self._enemy_types: list[dict] = []
        self._enemies:     list[dict] = []
        self._orig_enemy_types: list[dict] = []
        self._orig_enemies: list[dict] = []
        self._item_names: dict[int, str] = {}
        self._enemy_cat_entries: dict[str, list[str]] = {}
        self._enemy_palette_chunks: list[dict] = []
        self._modified       = False
        self._loading        = False
        self._cross_selecting = False   # re-entrance guard for list cross-links

        self._active_type_idx: int = -1   # type currently shown in right panel
        self._active_enc_idx:  int = -1   # encounter currently shown (-1 = none)

        self._tf: dict = {}   # type-form field widgets
        self._ef: dict = {}   # encounter-header field widgets

        self._type_items: dict[int, QTreeWidgetItem] = {}  # type_idx → tree item

        self._preview_paths: list[str] = []
        self._preview_idx:   int = 0

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # Title
        title = QLabel("Enemies Editor  —  DARKLAND.ENM")
        tf = title.font(); tf.setPointSize(11); tf.setBold(True); title.setFont(tf)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        main_split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(main_split, stretch=1)

        # ── Left: vertical splitter with two independent lists ────────────
        left_split = QSplitter(Qt.Orientation.Vertical)
        left_split.setMinimumWidth(175)
        left_split.setMaximumWidth(290)

        # ── Types list ─────────────────────────────────────────────
        type_panel = QWidget()
        type_vl = QVBoxLayout(type_panel)
        type_vl.setContentsMargins(0, 0, 0, 0)
        type_vl.setSpacing(2)
        type_hdr = QLabel("Enemy Types  (71 definitions)")
        type_hdr.setStyleSheet(
            "font-weight: bold; font-size: 8pt; color: #555;"
            " padding: 3px 4px; background: #f0f0f0; border-bottom: 1px solid #ddd;"
        )
        self._type_filter = QLineEdit()
        self._type_filter.setPlaceholderText("Filter enemy types...")
        self._type_filter.textChanged.connect(self._apply_type_filter)
        self._type_tree = QTreeWidget()
        self._type_tree.setHeaderHidden(True)
        self._type_tree.setAlternatingRowColors(False)
        self._type_tree.setFont(QFont("Courier New", 8))
        self._type_tree.setIndentation(14)
        self._type_tree.setRootIsDecorated(True)
        self._type_tree.currentItemChanged.connect(self._on_type_selected)
        type_vl.addWidget(type_hdr)
        type_vl.addWidget(self._type_filter)
        type_vl.addWidget(self._type_tree)
        left_split.addWidget(type_panel)

        # ── Encounters list ────────────────────────────────────────
        enc_panel = QWidget()
        enc_vl = QVBoxLayout(enc_panel)
        enc_vl.setContentsMargins(0, 0, 0, 0)
        enc_vl.setSpacing(2)
        enc_hdr = QLabel("Named Encounters  (82 entries)")
        enc_hdr.setStyleSheet(
            "font-weight: bold; font-size: 8pt; color: #555;"
            " padding: 3px 4px; background: #f0f0f0; border-bottom: 1px solid #ddd;"
        )
        self._enc_filter = QLineEdit()
        self._enc_filter.setPlaceholderText("Filter encounters...")
        self._enc_filter.textChanged.connect(self._apply_enc_filter)
        self._inst_list = QListWidget()
        self._inst_list.setAlternatingRowColors(False)
        self._inst_list.setFont(QFont("Courier New", 8))
        self._inst_list.currentRowChanged.connect(self._on_inst_selected)
        enc_vl.addWidget(enc_hdr)
        enc_vl.addWidget(self._enc_filter)
        enc_vl.addWidget(self._inst_list)
        left_split.addWidget(enc_panel)

        left_split.setSizes([320, 400])
        left_split.setCollapsible(0, False)
        left_split.setCollapsible(1, False)
        main_split.addWidget(left_split)

        # ── Right: scroll area with stacked form widgets ──────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._form_container = QWidget()
        self._form_vlay = QVBoxLayout(self._form_container)
        self._form_vlay.setContentsMargins(10, 10, 10, 10)
        self._form_vlay.setSpacing(10)

        self._placeholder = QLabel(
            "← Select an enemy type or a named encounter from the left panel"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            "color: #999; font-size: 10pt; font-style: italic;"
        )

        # Encounter card — shown above type form when an encounter is selected
        self._enc_card  = self._build_encounter_card()
        # Type form — always shown when anything is selected
        self._type_form = self._build_type_form()

        self._form_vlay.addWidget(self._placeholder)
        self._form_vlay.addWidget(self._enc_card)
        self._form_vlay.addWidget(self._type_form)
        self._form_vlay.addStretch()
        self._enc_card.hide()
        self._type_form.hide()
        self._scroll.setWidget(self._form_container)

        main_split.addWidget(self._scroll)
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        main_split.setSizes([220, 700])

        # ── Bottom action row ─────────────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.addStretch()
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #666; font-style: italic;")
        action_row.addWidget(self._status_lbl)
        self._undo_btn = QPushButton("Revert Current")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._undo_current)
        action_row.addWidget(self._undo_btn)
        self._save_btn = QPushButton("💾  Save to DARKLAND.ENM")
        self._save_btn.setEnabled(False)
        self._save_btn.setMinimumWidth(190)
        self._save_btn.clicked.connect(self._save_file)
        action_row.addWidget(self._save_btn)
        root.addLayout(action_row)

    # ── Type form ────────────────────────────────────────────────────────────

    def _build_type_form(self) -> QWidget:
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(10)
        f = self._tf

        # Small context label — changes text when accessed via encounter
        self._type_ctx_lbl = QLabel("ENEMY TYPE")
        self._type_ctx_lbl.setStyleSheet(
            "color: #888; font-size: 8pt; font-weight: bold; letter-spacing: 1px;"
        )
        vlay.addWidget(self._type_ctx_lbl)

        # ── Name header ───────────────────────────────────────────────────
        name_le = QLineEdit()
        name_le.setMaxLength(9)
        name_le.setPlaceholderText("Type name…")
        name_le.textEdited.connect(self._on_type_text_edited)
        nf = name_le.font(); nf.setPointSize(13); nf.setBold(True)
        name_le.setFont(nf)
        name_le.setStyleSheet(
            "QLineEdit { border: none; border-bottom: 2px solid #aaa;"
            " background: transparent; padding: 2px 0; }"
            "QLineEdit:focus { border-bottom-color: #4a90d9; }"
        )
        f['name'] = name_le
        vlay.addWidget(name_le)

        # ── Top two-column section ────────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Left column: Identity & Palette
        id_grp = self._section("Identity & Palette")
        id_fl  = QFormLayout(id_grp)
        id_fl.setSpacing(6)
        id_fl.setContentsMargins(10, 16, 10, 10)
        id_fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Image group: field + info label stacked
        ig_le = QLineEdit(); ig_le.setMaxLength(4)
        ig_le.setFixedWidth(52)
        ig_le.setToolTip("4-character sprite group ID — maps to PIC file(s) in the PICS folder")
        ig_le.textEdited.connect(self._on_type_text_edited)
        f['image_group'] = ig_le
        self._ig_info_lbl = QLabel("")
        self._ig_info_lbl.setStyleSheet("color: #888; font-size: 8pt;")
        self._ig_info_lbl.setWordWrap(True)
        ig_box = QWidget()
        ig_vl  = QVBoxLayout(ig_box); ig_vl.setContentsMargins(0, 0, 0, 0); ig_vl.setSpacing(2)
        ig_vl.addWidget(ig_le)
        ig_vl.addWidget(self._ig_info_lbl)
        id_fl.addRow("Image Group:", ig_box)

        # Variants with tooltip
        var_sb = QSpinBox(); var_sb.setRange(0, 255); var_sb.setFixedWidth(60)
        var_sb.valueChanged.connect(self._on_spin_changed)
        var_sb.setToolTip(
            "Number of graphical variants for this enemy type.\n"
            "Each variant is a separate sprite set (e.g. different colour schemes).\n"
            "Sprite files are named  <Image Group><variant index>.PIC"
        )
        f['num_variants'] = var_sb
        var_lbl = self._tip_label(
            "Variants:",
            "Number of graphical variants for this enemy type."
        )
        id_fl.addRow(var_lbl, var_sb)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ccc;")
        id_fl.addRow(sep)

        # Palette header mini-label
        pal_hdr = QLabel("Palette")
        ph_f = pal_hdr.font(); ph_f.setBold(True); ph_f.setPointSize(8)
        pal_hdr.setFont(ph_f)
        pal_hdr.setStyleSheet("color: #555;")
        id_fl.addRow(pal_hdr)

        pal_start_sb = QSpinBox(); pal_start_sb.setRange(0, 255); pal_start_sb.setFixedWidth(60)
        pal_start_sb.valueChanged.connect(self._on_spin_changed)
        f['pal_start'] = pal_start_sb
        ps_lbl = self._tip_label(
            "Pal Start:",
            "Index of the first palette slot (0–255) used by this enemy's sprites.\n"
            "The game loads pal_count colours starting at this index."
        )
        id_fl.addRow(ps_lbl, pal_start_sb)

        pal_cnt_sb = QSpinBox(); pal_cnt_sb.setRange(0, 255); pal_cnt_sb.setFixedWidth(60)
        pal_cnt_sb.valueChanged.connect(self._on_spin_changed)
        f['pal_cnt'] = pal_cnt_sb
        pc_lbl = self._tip_label(
            "Pal Count:",
            "Number of consecutive palette entries used (starting from Pal Start).\n"
            "Only these colours are loaded/replaced when the enemy appears."
        )
        id_fl.addRow(pc_lbl, pal_cnt_sb)

        top_row.addWidget(id_grp, stretch=1)

        # Right column: Sprite Preview
        prev_grp = self._section("Sprite Preview")
        prev_vl  = QVBoxLayout(prev_grp)
        prev_vl.setContentsMargins(8, 16, 8, 8)
        prev_vl.setSpacing(6)

        self._preview_label = QLabel("No image")
        self._preview_label.setFixedSize(self._PV_W, self._PV_H)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet(
            "QLabel { background: #1a1a1a; color: #666; border: 1px solid #444;"
            " border-radius: 3px; font-size: 8pt; }"
        )
        prev_vl.addWidget(self._preview_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Variant navigation
        nav = QHBoxLayout(); nav.setSpacing(4)
        self._prev_var_btn = QPushButton("◄")
        self._prev_var_btn.setFixedWidth(28)
        self._prev_var_btn.setEnabled(False)
        self._prev_var_btn.clicked.connect(self._prev_variant)
        self._variant_lbl = QLabel("—")
        self._variant_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._variant_lbl.setStyleSheet("font-size: 8pt; color: #888;")
        self._next_var_btn = QPushButton("►")
        self._next_var_btn.setFixedWidth(28)
        self._next_var_btn.setEnabled(False)
        self._next_var_btn.clicked.connect(self._next_variant)
        nav.addStretch()
        nav.addWidget(self._prev_var_btn)
        nav.addWidget(self._variant_lbl, stretch=1)
        nav.addWidget(self._next_var_btn)
        nav.addStretch()
        prev_vl.addLayout(nav)

        self._sprite_src_lbl = QLabel("")
        self._sprite_src_lbl.setWordWrap(True)
        self._sprite_src_lbl.setStyleSheet("font-size: 8pt; color: #888;")
        prev_vl.addWidget(self._sprite_src_lbl)

        self._validation_lbl = QLabel("")
        self._validation_lbl.setWordWrap(True)
        self._validation_lbl.setStyleSheet("font-size: 8pt; color: #b36b00;")
        prev_vl.addWidget(self._validation_lbl)

        self._changes_lbl = QLabel("")
        self._changes_lbl.setWordWrap(True)
        self._changes_lbl.setStyleSheet("font-size: 8pt; color: #5a86b8;")
        prev_vl.addWidget(self._changes_lbl)

        top_row.addWidget(prev_grp, stretch=0)
        vlay.addLayout(top_row)

        # ── Attributes ────────────────────────────────────────────────────
        attr_grp = self._section("Attributes")
        attr_outer = QVBoxLayout(attr_grp)
        attr_outer.setContentsMargins(10, 16, 10, 10)
        attr_row = QHBoxLayout()
        attr_row.setSpacing(6)
        for k in _ATTR_KEYS:
            cell = QWidget(); cell.setFixedWidth(76)
            cv = QVBoxLayout(cell); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(2)
            lbl = QLabel(_ATTR_LABELS[k])
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 8pt; font-weight: bold;")
            lbl.setWordWrap(True)
            sb = QSpinBox(); sb.setRange(0, 255)
            sb.valueChanged.connect(lambda v, key=k: self._type_field_changed('attr', key, v))
            cv.addWidget(lbl)
            cv.addWidget(sb)
            f[f'attr_{k}'] = sb
            attr_row.addWidget(cell)
        attr_row.addStretch()
        attr_outer.addLayout(attr_row)
        vlay.addWidget(attr_grp)

        # ── Skills ────────────────────────────────────────────────────────
        skill_grp = self._section("Skills")
        skill_outer = QVBoxLayout(skill_grp)
        skill_outer.setContentsMargins(10, 16, 10, 10)
        skill_outer.setSpacing(6)
        SCOLS = 5
        for row_i, row_start in enumerate(range(0, len(_SKILL_KEYS), SCOLS)):
            chunk = _SKILL_KEYS[row_start:row_start + SCOLS]
            row_hl = QHBoxLayout(); row_hl.setSpacing(6)
            for k in chunk:
                cell = QWidget(); cell.setFixedWidth(92)
                cv = QVBoxLayout(cell); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(2)
                lbl = QLabel(_SKILL_LABELS[k])
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("font-size: 8pt;")
                lbl.setWordWrap(True)
                sb = QSpinBox(); sb.setRange(0, 255)
                sb.valueChanged.connect(lambda v, key=k: self._type_field_changed('skill', key, v))
                cv.addWidget(lbl)
                cv.addWidget(sb)
                f[f'skill_{k}'] = sb
                row_hl.addWidget(cell)
            row_hl.addStretch()
            skill_outer.addLayout(row_hl)
            if row_i < (len(_SKILL_KEYS) - 1) // SCOLS:
                sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
                skill_outer.addWidget(sep)
        vlay.addWidget(skill_grp)

        # ── Armor & Weapons ───────────────────────────────────────────────
        combat_grp = self._section("Armor & Weapons")
        combat_fl  = QFormLayout(combat_grp)
        combat_fl.setContentsMargins(10, 16, 10, 10)
        combat_fl.setSpacing(6)
        combat_fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for key, lbl_text in (
            ('vital_arm_type',    "Vital Arm Type:"),
            ('limb_arm_typetype', "Limb Arm Type:"),
            ('armor_q',           "Armor Quality:"),
            ('shield_type',       "Shield Type:"),
            ('shield_q',          "Shield Quality:"),
        ):
            sb = QSpinBox(); sb.setRange(0, 255); sb.setFixedWidth(60)
            sb.valueChanged.connect(self._on_spin_changed)
            combat_fl.addRow(lbl_text, sb)
            f[key] = sb

        # Weapon types: 6 bytes in a row
        wrow = QHBoxLayout(); wrow.setSpacing(4)
        for i in range(6):
            sb = QSpinBox(); sb.setRange(0, 255); sb.setFixedWidth(52)
            sb.setToolTip(f"Weapon type slot {i}")
            sb.valueChanged.connect(lambda v, idx=i: self._type_field_changed('wtype', idx, v))
            wrow.addWidget(sb)
            f[f'weapon_type_{i}'] = sb
        wrow.addStretch()
        wbox = QWidget(); wbox.setLayout(wrow)
        combat_fl.addRow("Weapon Types:", wbox)

        wq_sb = QSpinBox(); wq_sb.setRange(0, 255); wq_sb.setFixedWidth(60)
        wq_sb.valueChanged.connect(self._on_spin_changed)
        combat_fl.addRow("Weapon Quality:", wq_sb)
        f['weapon_q'] = wq_sb

        vlay.addWidget(combat_grp)

        # ── Unknowns (collapsible-style, subdued) ─────────────────────────
        unk_grp = self._section("Unknown Fields  (read-only)")
        unk_grp.setStyleSheet(
            "QGroupBox { color: #888; border-color: #ccc; }"
            "QGroupBox::title { color: #999; }"
        )
        unk_fl  = QFormLayout(unk_grp)
        unk_fl.setContentsMargins(10, 16, 10, 10)
        unk_fl.setSpacing(4)
        unk_fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for key, label in (('unknown2', 'unk2'), ('unknown4', 'unk4 (word)'),
                           ('unknown5', 'unk5'), ('unknown6', 'unk6'),
                           ('unknown7', 'unk7'), ('unknown11', 'unk11')):
            le = QLineEdit(); le.setReadOnly(True); le.setFixedWidth(90)
            le.setStyleSheet("color: #888; background: #f5f5f5;")
            unk_fl.addRow(label + ":", le)
            f[f'ro_{key}'] = le
        for key, label in (('unknown8', 'unk8 (66 B)'), ('unknown9', 'unk9 (30 B)'),
                           ('unknown10', 'unk10 (2 B)'), ('unknown12', 'unk12 (6 B)'),
                           ('unknown13', 'unk13 (6 B)'), ('unknown14', 'unk14 (11 B)'),
                           ('unknown15', 'unk15 (20 B)')):
            le = QLineEdit(); le.setReadOnly(True)
            le.setStyleSheet("color: #888; background: #f5f5f5; font-size: 8pt;")
            unk_fl.addRow(label + ":", le)
            f[f'ro_{key}'] = le

        vlay.addWidget(unk_grp)
        vlay.addStretch()
        return w

    # ── Encounter card — shown above type form when encounter is selected ────

    def _build_encounter_card(self) -> QFrame:
        """
        A visually distinct card showing encounter-specific data.
        Appears above the type form when a Named Encounter is selected.
        """
        card = QFrame()
        card.setFrameShape(QFrame.Shape.NoFrame)
        card.setStyleSheet("""
            QFrame#EncCard {
                border-left: 4px solid #5577bb;
                padding-left: 10px;
            }
        """)
        card.setObjectName("EncCard")
        vl = QVBoxLayout(card)
        vl.setContentsMargins(12, 10, 12, 10)
        vl.setSpacing(5)
        f = self._ef

        # Section tag
        tag = QLabel("NAMED ENCOUNTER")
        tag.setStyleSheet("font-size: 8pt; font-weight: bold; letter-spacing: 1px; opacity: 0.6;")
        vl.addWidget(tag)

        # Encounter name (large editable)
        name_le = QLineEdit()
        name_le.setMaxLength(11)
        name_le.setPlaceholderText("Encounter name…")
        name_le.textEdited.connect(self._on_inst_text_edited)
        nf = name_le.font(); nf.setPointSize(12); nf.setBold(True)
        name_le.setFont(nf)
        f['name'] = name_le
        vl.addWidget(name_le)

        # Type selector row
        type_row = QHBoxLayout(); type_row.setSpacing(8)
        type_row.addWidget(QLabel("References type:"))
        type_sb = QSpinBox()
        type_sb.setRange(0, _ETYPE_COUNT - 1)
        type_sb.setFixedWidth(58)
        type_sb.setToolTip(
            "Index into the Enemy Types table (0–70).\n"
            "Changing this re-links the encounter to a different type definition."
        )
        type_sb.valueChanged.connect(self._inst_type_changed)
        f['type'] = type_sb
        type_row.addWidget(type_sb)
        self._enc_type_name_lbl = QLabel("")
        self._enc_type_name_lbl.setStyleSheet("font-weight: bold;")
        type_row.addWidget(self._enc_type_name_lbl)
        type_row.addStretch()
        vl.addLayout(type_row)

        # Unknown word field (read-only, inline)
        unk_row = QHBoxLayout(); unk_row.setSpacing(8)
        unk_row.addWidget(QLabel("Unknown word:"))
        unk_le = QLineEdit(); unk_le.setReadOnly(True); unk_le.setFixedWidth(80)
        f['ro_unknown'] = unk_le
        unk_row.addWidget(unk_le)
        unk_row.addStretch()
        vl.addLayout(unk_row)

        # Shared-by notice
        self._shared_notice = QLabel("")
        self._shared_notice.setStyleSheet("font-size: 8pt; padding: 3px 0 0 0;")
        self._shared_notice.setWordWrap(True)
        vl.addWidget(self._shared_notice)

        return card

    # ── Widget factory helpers ────────────────────────────────────────────────

    def _section(self, title: str) -> QGroupBox:
        """Create a consistently styled QGroupBox section."""
        grp = QGroupBox(title)
        grp.setStyleSheet(
            "QGroupBox { font-weight: bold; font-size: 9pt;"
            " border: 1px solid #c8c8c8; border-radius: 4px; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px;"
            " padding: 0 4px; color: #444; }"
        )
        return grp

    def _tip_label(self, text: str, tip: str) -> QLabel:
        """Label with a tooltip; appends a small ⓘ hint."""
        lbl = QLabel(text + " ⓘ")
        lbl.setToolTip(tip)
        lbl.setStyleSheet("QLabel { color: #444; }")
        return lbl

    def _le(self, fl: QFormLayout, label: str, maxlen: int,
            callback=None) -> QLineEdit:
        le = QLineEdit(); le.setMaxLength(maxlen)
        if callback:
            le.textEdited.connect(callback)
        fl.addRow(label, le)
        return le

    def _sb(self, fl: QFormLayout, label: str, lo: int, hi: int) -> QSpinBox:
        sb = QSpinBox(); sb.setRange(lo, hi)
        sb.valueChanged.connect(self._on_spin_changed)
        fl.addRow(label, sb)
        return sb

    # ── Path / load ──────────────────────────────────────────────────────────

    def set_dl_path(self, path: str):
        if path == self.dl_path:
            return
        self.dl_path = path
        if path:
            self._needs_refresh = True
            if self.isVisible():
                QTimer.singleShot(80, self._load_safe)

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh and self.dl_path:
            QTimer.singleShot(50, self._load_safe)

    def _load_safe(self):
        if not self._needs_refresh:
            return
        self._needs_refresh = False
        try:
            self._load()
        except Exception:
            self._needs_refresh = True
            self._status_lbl.setText(f"Load error: {traceback.format_exc(limit=2)}")

    def _load(self):
        from darklands.reader_enm import readData
        from collections import Counter, OrderedDict
        self._enemy_types, self._enemies = readData(self.dl_path)
        self._orig_enemy_types = copy.deepcopy(self._enemy_types)
        self._orig_enemies = copy.deepcopy(self._enemies)
        self._item_names = {}
        self._enemy_cat_entries = {}
        self._enemy_palette_chunks = []
        try:
            from darklands.reader_lst import readData as read_lst
            items, _, _ = read_lst(self.dl_path)
            self._item_names = {
                idx: item.get('name', '').strip()
                for idx, item in enumerate(items)
            }
        except Exception:
            self._item_names = {}
        try:
            from darklands.extract_cat import listContents
            for cat_name in ('E00C.CAT', 'M00C.CAT'):
                cat_path = os.path.join(self.dl_path, cat_name)
                if os.path.isfile(cat_path):
                    self._enemy_cat_entries[cat_name] = [
                        name for name, _, _ in listContents(cat_path)
                    ]
        except Exception:
            self._enemy_cat_entries = {}
        try:
            from darklands.reader_enemypal import readData as read_enemy_pals
            self._enemy_palette_chunks = read_enemy_pals(self.dl_path)
        except Exception:
            self._enemy_palette_chunks = []
        self._modified = False
        self._save_btn.setEnabled(False)
        self._undo_btn.setEnabled(False)
        self._active_type_idx = -1
        self._active_enc_idx  = -1

        # Count how many encounters reference each type
        enc_counts = Counter(e['type'] for e in self._enemies)

        # Group types by stripping trailing digits from the name.
        # e.g. Knight1, Knight2, Knight3 → group under Knight1.
        groups: list[list[int]] = []
        base_to_group: dict[str, int] = {}
        for i, et in enumerate(self._enemy_types):
            base = re.sub(r'\d+$', '', et['name'])
            if base in base_to_group:
                groups[base_to_group[base]].append(i)
            else:
                base_to_group[base] = len(groups)
                groups.append([i])

        self._loading = True
        self._type_tree.clear()
        self._type_items.clear()

        for group in groups:
            master_idx = group[0]
            et_m = self._enemy_types[master_idx]
            cnt_m = enc_counts.get(master_idx, 0)
            badge_m = f"  ×{cnt_m}" if cnt_m else "  ·"

            parent = QTreeWidgetItem(self._type_tree)
            parent.setText(0, f"{master_idx:2d}  {et_m['name']:<12}{badge_m}")
            parent.setData(0, Qt.ItemDataRole.UserRole, master_idx)
            self._type_items[master_idx] = parent

            for child_idx in group[1:]:
                etc = self._enemy_types[child_idx]
                cnt_c = enc_counts.get(child_idx, 0)
                badge_c = f"  ×{cnt_c}" if cnt_c else "  ·"
                child = QTreeWidgetItem(parent)
                child.setText(0, f"{child_idx:2d}  {etc['name']:<12}{badge_c}")
                child.setData(0, Qt.ItemDataRole.UserRole, child_idx)
                self._type_items[child_idx] = child

            if len(group) > 1:
                parent.setExpanded(True)

        self._inst_list.clear()
        for i, e in enumerate(self._enemies):
            self._inst_list.addItem(f"{i:2d}  {e['name']}")
        self._loading = False

        self._placeholder.show()
        self._enc_card.hide()
        self._type_form.hide()
        self._status_lbl.setText(
            f"Loaded {len(self._enemy_types)} types, {len(self._enemies)} encounters."
        )
        self._apply_type_filter()
        self._apply_enc_filter()

    def focus_filter(self):
        self._type_filter.setFocus()
        self._type_filter.selectAll()

    def select_type(self, idx: int):
        item = self._type_items.get(idx)
        if item is not None:
            self._type_tree.setCurrentItem(item)
            self._type_tree.scrollToItem(item)

    def select_encounter(self, idx: int):
        if 0 <= idx < self._inst_list.count():
            self._inst_list.setCurrentRow(idx)
            self._inst_list.scrollToItem(self._inst_list.item(idx))

    def _apply_type_filter(self):
        needle = self._type_filter.text().strip().lower()
        first_match = None
        for i in range(self._type_tree.topLevelItemCount()):
            parent = self._type_tree.topLevelItem(i)
            parent_match = not needle or needle in parent.text(0).lower()
            child_visible = False
            for j in range(parent.childCount()):
                child = parent.child(j)
                visible = not needle or needle in child.text(0).lower()
                child.setHidden(not visible)
                child_visible = child_visible or visible
                if visible and first_match is None:
                    first_match = child
            visible_parent = parent_match or child_visible
            parent.setHidden(not visible_parent)
            if visible_parent and first_match is None:
                first_match = parent
        current = self._type_tree.currentItem()
        if current is not None and current.isHidden() and first_match is not None:
            self._type_tree.setCurrentItem(first_match)

    def _apply_enc_filter(self):
        needle = self._enc_filter.text().strip().lower()
        first_visible = -1
        for row in range(self._inst_list.count()):
            item = self._inst_list.item(row)
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = row
        current = self._inst_list.currentRow()
        if current >= 0 and self._inst_list.item(current).isHidden() and first_visible >= 0:
            self._inst_list.setCurrentRow(first_visible)

    def _item_hint(self, item_idx: int) -> str:
        name = self._item_names.get(item_idx, "")
        if name:
            return f"Item #{item_idx}: {name}"
        return f"Item #{item_idx}"

    def _matching_enemy_imcs(self, image_group: str) -> list[str]:
        image_group = (image_group or "").upper().strip()
        if image_group.startswith('E'):
            pool = self._enemy_cat_entries.get('E00C.CAT', [])
        elif image_group.startswith('M'):
            pool = self._enemy_cat_entries.get('M00C.CAT', [])
        else:
            return []
        return [name for name in pool if name.upper().startswith(image_group)]

    def _palette_summary(self, pal_start: int, pal_cnt: int) -> str:
        if not self._enemy_palette_chunks:
            return "ENEMYPAL.DAT not loaded"
        matches = []
        for chunk in self._enemy_palette_chunks:
            idx = chunk.get('index', 0)
            if pal_start <= idx < pal_start + max(1, pal_cnt):
                start = chunk.get('start_index', 0)
                matches.append(f"#{idx} -> slots {start}-{start + 15}")
        if matches:
            return "Palette chunks: " + ", ".join(matches)
        return f"Palette chunks: start={pal_start}, count={pal_cnt}"

    def _enemy_preview_palette(self, pal_start: int, pal_cnt: int):
        from darklands.palette_context import load_combat_palette
        palette = load_combat_palette(self.dl_path)
        matches = [
            chunk for chunk in self._enemy_palette_chunks
            if pal_start <= chunk.get('index', -1) < pal_start + max(1, pal_cnt)
        ]
        if matches:
            chunk = matches[0]
            start = chunk.get('start_index', 0)
            for offset, color in enumerate(chunk.get('colors', [])):
                slot = start + offset
                if 0 <= slot < len(palette):
                    palette[slot] = color
        return palette

    def _refresh_sprite_sources(self, image_group: str, pal_start: int, pal_cnt: int):
        matches = self._matching_enemy_imcs(image_group)
        lines = [self._palette_summary(pal_start, pal_cnt)]
        if matches:
            cat_name = 'E00C.CAT' if image_group.upper().startswith('E') else 'M00C.CAT'
            preview = ", ".join(matches[:4])
            if len(matches) > 4:
                preview += f", ... (+{len(matches) - 4} more)"
            lines.append(f"{cat_name}: {preview}")
            self._sprite_src_lbl.setToolTip("\n".join(matches))
        else:
            lines.append("No matching IMC entries found in enemy CAT catalogs")
            self._sprite_src_lbl.setToolTip("")
        self._sprite_src_lbl.setText("\n".join(lines))

    def _refresh_combat_tooltips(self):
        f = self._tf
        for key in ('vital_arm_type', 'limb_arm_typetype', 'shield_type'):
            if key in f:
                value = f[key].value()
                f[key].setToolTip(self._item_hint(value))
        for i in range(6):
            key = f'weapon_type_{i}'
            if key in f:
                value = f[key].value()
                f[key].setToolTip(self._item_hint(value))

    def _refresh_editor_highlights(self):
        if 0 <= self._active_type_idx < len(self._enemy_types) and self._orig_enemy_types:
            cur = self._enemy_types[self._active_type_idx]
            orig = self._orig_enemy_types[self._active_type_idx]
            _set_widget_edited(self._tf['name'], cur.get('name', '') != orig.get('name', ''))
            _set_widget_edited(self._tf['image_group'], cur.get('image_group', '') != orig.get('image_group', ''))
            for key in ('num_variants', 'pal_start', 'pal_cnt', 'vital_arm_type', 'limb_arm_typetype', 'armor_q', 'shield_type', 'shield_q', 'weapon_q'):
                _set_widget_edited(self._tf[key], cur.get(key, 0) != orig.get(key, 0))
            for key in _ATTR_KEYS:
                _set_widget_edited(self._tf[f'attr_{key}'], cur['attrs'].get(key, 0) != orig['attrs'].get(key, 0))
            for key in _SKILL_KEYS:
                _set_widget_edited(self._tf[f'skill_{key}'], cur['skills'].get(key, 0) != orig['skills'].get(key, 0))
            for i in range(6):
                cur_val = cur['weapon_types'][i] if i < len(cur['weapon_types']) else 0
                orig_val = orig['weapon_types'][i] if i < len(orig['weapon_types']) else 0
                _set_widget_edited(self._tf[f'weapon_type_{i}'], cur_val != orig_val)
        if 0 <= self._active_enc_idx < len(self._enemies) and self._orig_enemies:
            cur = self._enemies[self._active_enc_idx]
            orig = self._orig_enemies[self._active_enc_idx]
            _set_widget_edited(self._ef['name'], cur.get('name', '') != orig.get('name', ''))
            _set_widget_edited(self._ef['type'], cur.get('type', -1) != orig.get('type', -1))
        self._undo_btn.setEnabled(self._current_has_changes())

    def _current_has_changes(self) -> bool:
        type_changed = (
            0 <= self._active_type_idx < len(self._enemy_types)
            and self._orig_enemy_types
            and self._enemy_types[self._active_type_idx] != self._orig_enemy_types[self._active_type_idx]
        )
        if 0 <= self._active_enc_idx < len(self._enemies) and self._orig_enemies:
            return (
                self._enemies[self._active_enc_idx] != self._orig_enemies[self._active_enc_idx]
                or type_changed
            )
        if type_changed:
            return True
        return False

    def _refresh_modified_state(self):
        self._modified = (
            self._enemy_types != self._orig_enemy_types
            or self._enemies != self._orig_enemies
        )
        self._save_btn.setEnabled(self._modified)
        self._undo_btn.setEnabled(self._current_has_changes())
        if self._modified:
            dirty_types = sum(
                1 for cur, orig in zip(self._enemy_types, self._orig_enemy_types)
                if cur != orig
            )
            dirty_encounters = sum(
                1 for cur, orig in zip(self._enemies, self._orig_enemies)
                if cur != orig
            )
            current_note = " Current selection differs from loaded data." if self._current_has_changes() else ""
            self._status_lbl.setText(
                f"Unsaved changes: {dirty_types} enemy type(s), {dirty_encounters} encounter(s).{current_note}"
            )
        elif self._status_lbl.text().startswith("Unsaved changes:"):
            self._status_lbl.setText("No unsaved enemy changes.")
        self._refresh_list_markers()
        self._refresh_detail_panels()
        self._refresh_editor_highlights()

    def _type_change_count(self, idx: int) -> int:
        if idx < 0 or idx >= len(self._enemy_types) or not self._orig_enemy_types:
            return 0
        et = self._enemy_types[idx]
        orig = self._orig_enemy_types[idx]
        count = 0
        for key in (
            "name", "image_group", "num_variants", "pal_start", "pal_cnt",
            "vital_arm_type", "limb_arm_typetype", "armor_q", "shield_type",
            "shield_q", "weapon_q",
        ):
            count += int(et.get(key) != orig.get(key))
        count += int(et.get("attrs") != orig.get("attrs"))
        count += int(et.get("skills") != orig.get("skills"))
        count += int(bytes(et.get("weapon_types", b"")) != bytes(orig.get("weapon_types", b"")))
        return count

    def _enc_change_count(self, idx: int) -> int:
        if idx < 0 or idx >= len(self._enemies) or not self._orig_enemies:
            return 0
        cur = self._enemies[idx]
        orig = self._orig_enemies[idx]
        return int(cur.get("name") != orig.get("name")) + int(cur.get("type") != orig.get("type"))

    def _refresh_list_markers(self):
        if not self._orig_enemy_types or not self._orig_enemies:
            return
        from collections import Counter
        counts = Counter(e['type'] for e in self._enemies)
        for idx, item in self._type_items.items():
            et = self._enemy_types[idx]
            cnt = counts.get(idx, 0)
            badge = f"  x{cnt}" if cnt else "  ."
            dirty = self._type_change_count(idx)
            marker = f"  *{dirty}" if dirty else ""
            item.setText(0, f"{idx:2d}  {et['name']:<12}{badge}{marker}")
        for idx in range(self._inst_list.count()):
            enc = self._enemies[idx]
            dirty = self._enc_change_count(idx)
            marker = f"  *{dirty}" if dirty else ""
            self._inst_list.item(idx).setText(f"{idx:2d}  {enc['name']}{marker}")

    def _type_validation_messages(self, et: dict) -> list[str]:
        msgs = []
        image_group = et.get('image_group', '').strip()
        pal_start = int(et.get('pal_start', 0))
        pal_cnt = int(et.get('pal_cnt', 0))
        num_variants = int(et.get('num_variants', 0))
        if not image_group:
            msgs.append("Missing image group.")
        elif not self._matching_enemy_imcs(image_group):
            msgs.append("No matching IMC sprite sources found.")
        if pal_cnt <= 0:
            msgs.append("Palette count is zero.")
        if pal_start + max(1, pal_cnt) > len(self._enemy_palette_chunks):
            msgs.append("Palette range extends beyond loaded ENEMYPAL entries.")
        if num_variants <= 0:
            msgs.append("Variant count is zero.")
        bad_items = []
        for key in ('vital_arm_type', 'limb_arm_typetype', 'shield_type'):
            item_idx = int(et.get(key, 0))
            if item_idx and item_idx not in self._item_names:
                bad_items.append(f"{key}={item_idx}")
        for item_idx in et.get('weapon_types', []):
            item_idx = int(item_idx)
            if item_idx and item_idx not in self._item_names:
                bad_items.append(f"weapon={item_idx}")
        if bad_items:
            msgs.append("Unknown item references: " + ", ".join(bad_items[:4]) + (" ..." if len(bad_items) > 4 else ""))
        return msgs

    def _enc_validation_messages(self, enc: dict) -> list[str]:
        msgs = []
        type_idx = int(enc.get('type', -1))
        if not (0 <= type_idx < len(self._enemy_types)):
            msgs.append(f"Encounter type index {type_idx} is out of range.")
        return msgs

    def _current_change_summary(self) -> list[str]:
        lines = []
        if 0 <= self._active_type_idx < len(self._enemy_types) and self._orig_enemy_types:
            cur = self._enemy_types[self._active_type_idx]
            orig = self._orig_enemy_types[self._active_type_idx]
            changed = []
            for key in ('name', 'image_group', 'num_variants', 'pal_start', 'pal_cnt',
                        'vital_arm_type', 'limb_arm_typetype', 'armor_q', 'shield_type',
                        'shield_q', 'weapon_q'):
                if cur.get(key) != orig.get(key):
                    changed.append(key)
            for key in _ATTR_KEYS:
                if cur['attrs'].get(key) != orig['attrs'].get(key):
                    changed.append(f"attr:{key}")
            for key in _SKILL_KEYS:
                if cur['skills'].get(key) != orig['skills'].get(key):
                    changed.append(f"skill:{key}")
            for i, (cv, ov) in enumerate(zip(cur.get('weapon_types', []), orig.get('weapon_types', []))):
                if cv != ov:
                    changed.append(f"weapon_type_{i}")
            if changed:
                lines.append("Type changes: " + ", ".join(changed[:10]) + (" ..." if len(changed) > 10 else ""))
        if 0 <= self._active_enc_idx < len(self._enemies) and self._orig_enemies:
            cur = self._enemies[self._active_enc_idx]
            orig = self._orig_enemies[self._active_enc_idx]
            changed = [key for key in ('name', 'type') if cur.get(key) != orig.get(key)]
            if changed:
                lines.append("Encounter changes: " + ", ".join(changed))
        return lines

    def _refresh_detail_panels(self):
        messages = []
        et = self._current_type()
        if et is not None:
            messages.extend(self._type_validation_messages(et))
        enc = self._current_enc()
        if enc is not None:
            messages.extend(self._enc_validation_messages(enc))
        self._validation_lbl.setText("Warnings: " + " ".join(messages) if messages else "Warnings: none.")

        summary = self._current_change_summary()
        self._changes_lbl.setText("Changed: " + " ".join(summary) if summary else "Changed: current selection matches loaded data.")

    # ── Selection handlers ────────────────────────────────────────────────────

    def _on_type_selected(self, current: QTreeWidgetItem, previous):
        """User clicked in the Enemy Types tree."""
        if self._loading or self._cross_selecting or current is None:
            return
        idx = current.data(0, Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        self._active_type_idx = idx
        self._active_enc_idx  = -1
        # Deselect encounter list
        self._cross_selecting = True
        self._inst_list.setCurrentRow(-1)
        self._cross_selecting = False
        # Highlight matching encounters
        self._highlight_encounters(idx)
        self._show_type_form(idx, via_encounter=False)

    def _on_inst_selected(self, row: int):
        """User clicked in the Named Encounters list."""
        if self._loading or self._cross_selecting or row < 0:
            return
        self._active_enc_idx  = row
        e = self._enemies[row]
        type_idx = e['type']
        self._active_type_idx = type_idx
        # Mirror-select the type in the tree (no feedback loop)
        tree_item = self._type_items.get(type_idx)
        if tree_item is not None:
            self._cross_selecting = True
            self._type_tree.setCurrentItem(tree_item)
            self._type_tree.scrollToItem(tree_item)
            self._cross_selecting = False
        # Remove per-encounter highlighting
        self._clear_encounter_highlight()
        # Show encounter card + type form
        self._populate_enc_card(row)
        self._show_type_form(type_idx, via_encounter=True)

    # ── Cross-highlighting ────────────────────────────────────────────────────

    def _highlight_encounters(self, type_idx: int):
        """Blue for encounters that use type_idx, dim for all others."""
        for j in range(self._inst_list.count()):
            item = self._inst_list.item(j)
            if self._enemies[j]['type'] == type_idx:
                item.setForeground(self._BRUSH_MATCH)
            else:
                item.setForeground(self._BRUSH_DIM)

    def _clear_encounter_highlight(self):
        for j in range(self._inst_list.count()):
            self._inst_list.item(j).setForeground(self._BRUSH_DEFAULT)

    # ── Populate encounter card ───────────────────────────────────────────────

    def _populate_enc_card(self, idx: int):
        e = self._enemies[idx]
        f = self._ef
        self._loading = True
        f['name'].setText(e['name'])
        f['type'].setValue(e['type'])
        self._enc_type_name_lbl.setText(e.get('type_str', ''))
        f['ro_unknown'].setText(f"0x{e['unknown']:04X}")
        # How many encounters share this type?
        shared = sum(1 for x in self._enemies if x['type'] == e['type'])
        if shared > 1:
            self._shared_notice.setText(
                f"⚠  {shared} encounters share this type — editing stats below"
                f" affects all of them."
            )
        else:
            self._shared_notice.setText("")
        self._loading = False

    # ── Show type form ────────────────────────────────────────────────────────

    def _show_type_form(self, idx: int, *, via_encounter: bool = False):
        if idx < 0 or idx >= len(self._enemy_types):
            return
        et = self._enemy_types[idx]
        f  = self._tf
        self._loading = True
        f['name'].setText(et['name'])
        f['image_group'].setText(et['image_group'])
        f['num_variants'].setValue(et['num_variants'])
        f['pal_start'].setValue(et['pal_start'])
        f['pal_cnt'].setValue(et['pal_cnt'])
        for k in _ATTR_KEYS:
            f[f'attr_{k}'].setValue(et['attrs'][k])
        for k in _SKILL_KEYS:
            f[f'skill_{k}'].setValue(et['skills'][k])
        f['vital_arm_type'].setValue(et['vital_arm_type'])
        f['limb_arm_typetype'].setValue(et['limb_arm_typetype'])
        f['armor_q'].setValue(et['armor_q'])
        f['shield_type'].setValue(et['shield_type'])
        f['shield_q'].setValue(et['shield_q'])
        for i in range(6):
            f[f'weapon_type_{i}'].setValue(et['weapon_types'][i])
        f['weapon_q'].setValue(et['weapon_q'])
        for key in ('unknown2', 'unknown5', 'unknown6', 'unknown7', 'unknown11'):
            f[f'ro_{key}'].setText(f"0x{et[key]:02X}")
        f['ro_unknown4'].setText(f"0x{et['unknown4']:04X}")
        for key in ('unknown8', 'unknown9', 'unknown10', 'unknown12',
                    'unknown13', 'unknown14', 'unknown15'):
            f[f'ro_{key}'].setText(bytes(et[key]).hex(' '))
        self._loading = False
        self._refresh_editor_highlights()
        self._refresh_combat_tooltips()

        # Context label wording
        if via_encounter:
            self._type_ctx_lbl.setText("ENEMY TYPE  (shared definition)")
        else:
            self._type_ctx_lbl.setText("ENEMY TYPE")

        # Show/hide encounter card
        self._placeholder.hide()
        if via_encounter:
            self._enc_card.show()
        else:
            self._enc_card.hide()
        self._type_form.show()

        # Sprite preview
        self._update_preview(et['image_group'])
        self._refresh_sprite_sources(et['image_group'], et['pal_start'], et['pal_cnt'])
        self._refresh_detail_panels()
        self._refresh_editor_highlights()

    # ── Sprite preview ────────────────────────────────────────────────────────

    def _pics_dir(self) -> str:
        """Return best candidate directory for PIC files."""
        if not self.dl_path:
            return ""
        candidate = os.path.join(self.dl_path, "PICS")
        return candidate if os.path.isdir(candidate) else self.dl_path

    def _find_variant_pics(self, image_group: str) -> list[str]:
        pics_dir = self._pics_dir()
        if not pics_dir or not image_group:
            return []
        ig = image_group.upper()
        try:
            return sorted(
                os.path.join(pics_dir, f)
                for f in os.listdir(pics_dir)
                if f.upper().startswith(ig) and f.upper().endswith('.PIC')
            )
        except OSError:
            return []

    def _find_variant_sources(self, image_group: str):
        if image_group.upper().startswith(('E', 'M')):
            matches = self._matching_enemy_imcs(image_group)
            if matches:
                cat_name = 'E00C.CAT' if image_group.upper().startswith('E') else 'M00C.CAT'
                cat_path = os.path.join(self.dl_path, cat_name)
                return [('imc', cat_path, name) for name in matches]
        return [('pic', path, os.path.basename(path)) for path in self._find_variant_pics(image_group)]

    def _update_preview(self, image_group: str):
        paths = self._find_variant_sources(image_group)
        if paths:
            fnames = ", ".join(p[2] for p in paths[:6])
            if len(paths) > 6:
                fnames += f", ... (+{len(paths) - 6} more)"
            self._ig_info_lbl.setText(f"Found: {fnames}")
        else:
            self._ig_info_lbl.setText("No matching sprite assets found" if image_group else "")
        self._load_preview(paths, 0)

    def _load_preview(self, paths, idx: int):
        self._preview_paths = paths
        self._preview_idx   = max(0, min(idx, len(paths) - 1)) if paths else 0

        if not paths:
            self._preview_label.setPixmap(QPixmap())
            self._preview_label.setText("No image")
            self._prev_var_btn.setEnabled(False)
            self._next_var_btn.setEnabled(False)
            self._variant_lbl.setText("—")
            return

        kind, source, label = paths[self._preview_idx]
        try:
            if kind == 'pic':
                from darklands.format_pic import Pic, default_pal
                pic = Pic(source)
                if not pic.pal:
                    pic.pal = list(default_pal)
                if pic.pic:
                    rgba, w, h = pic.render_rgba_bytes()
                    img = QImage(rgba, w, h, QImage.Format.Format_ARGB32)
                    raw_pm = QPixmap.fromImage(img)
                    scaled = raw_pm.scaled(
                        self._PV_W, self._PV_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._preview_label.setPixmap(scaled)
                    self._preview_label.setText("")
                else:
                    self._preview_label.setPixmap(QPixmap())
                    self._preview_label.setText("(palette only)")
            else:
                from darklands.extract_cat import extractOneToBytes
                from darklands.reader_imc import readDataBytes, render_rgba
                _, raw = extractOneToBytes(source, label)
                imc = readDataBytes(raw, name=label)
                rows = imc.get('frames', [{}])[0].get('rows', []) if imc.get('frames') else []
                if not rows:
                    self._preview_label.setPixmap(QPixmap())
                    self._preview_label.setText("(no IMC frame)")
                else:
                    et = self._current_type() or {}
                    palette = self._enemy_preview_palette(et.get('pal_start', 0), et.get('pal_cnt', 0))
                    rgba, w, h = render_rgba(rows, palette)
                    img = QImage(rgba, w, h, QImage.Format.Format_ARGB32)
                    raw_pm = QPixmap.fromImage(img)
                    scaled = raw_pm.scaled(
                        self._PV_W, self._PV_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    self._preview_label.setPixmap(scaled)
                    self._preview_label.setText("")
        except Exception as exc:
            self._preview_label.setPixmap(QPixmap())
            self._preview_label.setText(f"Error:\n{exc}")

        fname = label if kind == 'imc' else os.path.basename(source)
        n = len(paths)
        self._variant_lbl.setText(f"{self._preview_idx + 1} / {n}   {fname}")
        self._prev_var_btn.setEnabled(n > 1)
        self._next_var_btn.setEnabled(n > 1)

    def _prev_variant(self):
        if not self._preview_paths:
            return
        n = len(self._preview_paths)
        self._load_preview(self._preview_paths, (self._preview_idx - 1) % n)

    def _next_variant(self):
        if not self._preview_paths:
            return
        n = len(self._preview_paths)
        self._load_preview(self._preview_paths, (self._preview_idx + 1) % n)

    # ── Field-change helpers (write back to dict) ────────────────────────────

    def _current_type(self) -> dict | None:
        return self._enemy_types[self._active_type_idx] \
            if 0 <= self._active_type_idx < len(self._enemy_types) else None

    def _current_enc(self) -> dict | None:
        return self._enemies[self._active_enc_idx] \
            if 0 <= self._active_enc_idx < len(self._enemies) else None

    def _mark_modified(self):
        if not self._loading:
            self._refresh_modified_state()

    def _undo_current(self):
        enc_changed = (
            0 <= self._active_enc_idx < len(self._enemies)
            and self._orig_enemies
            and self._enemies[self._active_enc_idx] != self._orig_enemies[self._active_enc_idx]
        )
        type_changed = (
            0 <= self._active_type_idx < len(self._enemy_types)
            and self._orig_enemy_types
            and self._enemy_types[self._active_type_idx] != self._orig_enemy_types[self._active_type_idx]
        )
        if enc_changed:
            self._enemies[self._active_enc_idx] = copy.deepcopy(self._orig_enemies[self._active_enc_idx])
            enc = self._enemies[self._active_enc_idx]
            self._refresh_list_markers()
            self._populate_enc_card(self._active_enc_idx)
            self._show_type_form(enc['type'], via_encounter=True)
            self._status_lbl.setText("Reverted current encounter.")
        elif type_changed:
            self._enemy_types[self._active_type_idx] = copy.deepcopy(self._orig_enemy_types[self._active_type_idx])
            et = self._enemy_types[self._active_type_idx]
            tree_item = self._type_items.get(self._active_type_idx)
            if tree_item is not None:
                count = sum(1 for x in self._enemies if x['type'] == self._active_type_idx)
                badge = f"  ×{count}" if count else "  ·"
                tree_item.setText(0, f"{self._active_type_idx:2d}  {et['name']:<12}{badge}")
            self._show_type_form(self._active_type_idx, via_encounter=False)
            self._status_lbl.setText("Reverted current enemy type.")
        self._refresh_modified_state()

    def _on_type_text_edited(self):
        if self._loading:
            return
        et = self._current_type()
        if et is None:
            return
        f = self._tf
        old_ig        = et['image_group']
        et['name']        = f['name'].text()
        et['image_group'] = f['image_group'].text()
        # Refresh type tree item (name + encounter count badge)
        from collections import Counter
        counts = Counter(e['type'] for e in self._enemies)
        row  = self._active_type_idx
        cnt  = counts.get(row, 0)
        badge = f"  ×{cnt}" if cnt else "  ·"
        item = self._type_items.get(row)
        if item is not None:
            item.setText(0, f"{row:2d}  {et['name']:<12}{badge}")
        if et['image_group'] != old_ig:
            self._update_preview(et['image_group'])
        self._refresh_sprite_sources(et['image_group'], et['pal_start'], et['pal_cnt'])
        self._mark_modified()

    def _on_inst_text_edited(self):
        if self._loading:
            return
        e = self._current_enc()
        if e is None:
            return
        e['name'] = self._ef['name'].text()
        row = self._active_enc_idx
        self._inst_list.item(row).setText(f"{row:2d}  {e['name']}")
        self._mark_modified()

    def _on_spin_changed(self):
        if self._loading:
            return
        # Encounter card type spinbox is handled by _inst_type_changed
        self._flush_type_spins()
        self._refresh_combat_tooltips()
        et = self._current_type()
        if et is not None:
            self._refresh_sprite_sources(et['image_group'], et['pal_start'], et['pal_cnt'])
        self._mark_modified()

    def _type_field_changed(self, group: str, key, value: int):
        if self._loading:
            return
        et = self._current_type()
        if et is None:
            return
        if group == 'attr':
            et['attrs'][key] = value
        elif group == 'skill':
            et['skills'][key] = value
        elif group == 'wtype':
            wt = bytearray(et['weapon_types'])
            wt[key] = value
            et['weapon_types'] = bytes(wt)
            self._refresh_combat_tooltips()
        self._mark_modified()

    def _flush_type_spins(self):
        et = self._current_type()
        if et is None:
            return
        f = self._tf
        et['num_variants']      = f['num_variants'].value()
        et['pal_start']         = f['pal_start'].value()
        et['pal_cnt']           = f['pal_cnt'].value()
        et['vital_arm_type']    = f['vital_arm_type'].value()
        et['limb_arm_typetype'] = f['limb_arm_typetype'].value()
        et['armor_q']           = f['armor_q'].value()
        et['shield_type']       = f['shield_type'].value()
        et['shield_q']          = f['shield_q'].value()
        et['weapon_q']          = f['weapon_q'].value()

    def _inst_type_changed(self, val: int):
        """Encounter card type spinbox changed — re-link to a different type."""
        if self._loading:
            return
        e = self._current_enc()
        if e is None:
            return
        old_type = e['type']
        e['type'] = val
        name = self._enemy_types[val]['name'] if 0 <= val < len(self._enemy_types) else '?'
        e['type_str'] = name
        self._enc_type_name_lbl.setText(name)
        # Mirror-select new type in tree
        self._active_type_idx = val
        new_item = self._type_items.get(val)
        if new_item is not None:
            self._cross_selecting = True
            self._type_tree.setCurrentItem(new_item)
            self._type_tree.scrollToItem(new_item)
            self._cross_selecting = False
        # Refresh shared notice
        shared = sum(1 for x in self._enemies if x['type'] == val)
        if shared > 1:
            self._shared_notice.setText(
                f"⚠  {shared} encounters share this type — editing stats below"
                f" affects all of them."
            )
        else:
            self._shared_notice.setText("")
        # Reload type form for the new type
        self._show_type_form(val, via_encounter=True)
        # Refresh tree item badges (old and new type counts changed)
        from collections import Counter
        counts = Counter(x['type'] for x in self._enemies)
        for tidx in {old_type, val}:
            tree_item = self._type_items.get(tidx)
            if tree_item is not None:
                et = self._enemy_types[tidx]
                cnt  = counts.get(tidx, 0)
                badge = f"  ×{cnt}" if cnt else "  ·"
                tree_item.setText(0, f"{tidx:2d}  {et['name']:<12}{badge}")
        self._mark_modified()

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save_file(self):
        if not self.dl_path:
            QMessageBox.warning(self, "No path", "DL data path is not set.")
            return
        if not _confirm_validation(
            self,
            self.dl_path,
            ("ENM", "ENM/LST", "ENM/ENEMYPAL"),
            {"enemy_types": self._enemy_types, "enemies": self._enemies},
            "Validation Warning",
        ):
            return
        fname = os.path.join(self.dl_path, 'DARKLAND.ENM')
        parts = [_encode_enemy_type(et) for et in self._enemy_types]
        parts += [_encode_enemy_instance(e) for e in self._enemies]
        data = b''.join(parts)
        try:
            backup = backup_existing_file(fname)
            with open(fname, 'wb') as fh:
                fh.write(data)
            self._orig_enemy_types = copy.deepcopy(self._enemy_types)
            self._orig_enemies = copy.deepcopy(self._enemies)
            self._modified = False
            self._save_btn.setEnabled(False)
            self._undo_btn.setEnabled(False)
            self._status_lbl.setText(
                f"Saved {len(data):,} bytes -> {os.path.basename(fname)} ({backup_label(backup)})"
            )
            self._refresh_editor_highlights()
        except OSError as exc:
            QMessageBox.critical(self, "Save error", str(exc))


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

class LocationsConverter(TextConverter):
    def __init__(self, parent=None):
        super().__init__("Locations (DARKLAND.LOC)", parent)

    def run(self):
        if self._need_dl_path():
            return
        from darklands.reader_loc import readData
        locs = readData(self.dl_path)
        buf = io.StringIO()
        buf.write(f"=== Locations ({len(locs)}) ===\n\n")
        for i, c in enumerate(locs):
            buf.write(f"{i:3d}: [{c['str_loc_type']:28s}]  "
                      f"{c['name']:20s}  coords={c['coords']}  "
                      f"size={c['city_size']}\n")
        self._show_text(buf.getvalue())


# ---------------------------------------------------------------------------
# Items, Saints & Formulae
# ---------------------------------------------------------------------------

class ItemsConverter(TextConverter):
    def __init__(self, parent=None):
        super().__init__("Items, Saints & Formulae (DARKLAND.LST)", parent)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show:"))
        self.section_combo = QComboBox()
        self.section_combo.addItems(["Items", "Saints", "Formulae"])
        self.section_combo.currentIndexChanged.connect(self._render)
        row.addWidget(self.section_combo)
        row.addStretch()
        self.input_layout.addLayout(row)
        self._cache = None

    def run(self):
        if self._need_dl_path():
            return
        from darklands.reader_lst import readData
        self._cache = readData(self.dl_path)
        self._render()

    def _render(self):
        if not self._cache:
            return
        items, saints, forms = self._cache
        section = self.section_combo.currentText()
        buf = io.StringIO()
        if section == "Items":
            buf.write(f"=== Items ({len(items)}) ===\n\n")
            for i, c in enumerate(items):
                flags = [k[3:] for k, v in c.items()
                         if k.startswith('is_') and v is True]
                buf.write(f"{i:3d}: {c['name']:22s}  type={c['type']:3d}  "
                          f"wt={c['weight']:3d}  q={c['quality']:3d}  "
                          f"val={c['value']:5d}  [{', '.join(flags)}]\n")
        elif section == "Saints":
            buf.write(f"=== Saints ({len(saints)}) ===\n\n")
            for i, s in enumerate(saints):
                buf.write(f"{i:3d}: {s['name']:20s}  ({s.get('short_name','')})\n")
                if s.get('description'):
                    buf.write(f"     {s['description'][:120]}\n")
                buf.write("\n")
        elif section == "Formulae":
            buf.write(f"=== Formulae ({len(forms)}) ===\n\n")
            for i, f in enumerate(forms):
                buf.write(f"{i:3d}: {f['name']:20s}  ({f.get('short_name','')})\n")
        self._show_text(buf.getvalue())


# ---------------------------------------------------------------------------
# World Map — interactive viewer / editor with location overlay
# Implemented in map_graphics.py; re-exported here as MapConverter so the
# existing main_window.py registry ("MapConverter") keeps working unchanged.
# ---------------------------------------------------------------------------

from .map_graphics import MapEditorWidget as MapConverter  # noqa: F401


# ---------------------------------------------------------------------------
# Cities
# ---------------------------------------------------------------------------

class CitiesConverter(TextConverter):
    def __init__(self, parent=None):
        super().__init__("Cities (DARKLAND.CTY)", parent)

    def run(self):
        if self._need_dl_path():
            return
        from darklands.format_cty import readData
        from darklands.utils import tchars
        cities = readData(self.dl_path)
        buf = io.StringIO()
        buf.write(f"=== Cities ({len(cities)}) ===\n\n")
        for i, c in enumerate(cities):
            buf.write(f"{i:3d}: {tchars(c.name):30s}  ({c.str_city_type})  "
                      f"size={c.city_size}  coords={c.entry_coords}\n")
            if c.dock_destinations:
                buf.write(f"     Docks → {c.str_dock_destinations}\n")
            buildings = [
                k[4:] for k, v in c.city_contents.items()
                if v and not k.startswith('has_no') and not k.startswith('has_const')
            ]
            if buildings:
                buf.write(f"     Has: {', '.join(buildings)}\n")
            quals = {
                k[5:]: v for k, v in vars(c).items()
                if k.startswith('qual_') and v
                and not k.endswith(('unk1', 'unk2', 'unk3'))
            }
            if quals:
                buf.write(f"     Quality: {quals}\n")
            buf.write("\n")
        self._show_text(buf.getvalue())
