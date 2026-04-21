import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QHeaderView,
)

from vendor.darklands.format_cty import CITY_CONTENT_FLAGS
from vendor.darklands.reader_loc import locTypes
from app.file_ops import backup_existing_file, backup_label
from app.validation import filter_issues, summarize_issues, validate_world_data


def _sep():
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.HLine)
    frame.setFrameShadow(QFrame.Shadow.Sunken)
    return frame


def _title(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSize(11)
    font.setBold(True)
    label.setFont(font)
    return label


_EDITED_STYLE = "background-color: rgba(215, 170, 47, 0.18);"


def _set_widget_edited(widget, edited: bool):
    base = widget.property("_base_style")
    if base is None:
        base = widget.styleSheet()
        widget.setProperty("_base_style", base)
    widget.setStyleSheet(f"{base}\n{_EDITED_STYLE}" if edited else base)


def _make_spin(min_v: int, max_v: int, *, width: int = 88, special_text: str | None = None) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(min_v, max_v)
    spin.setFixedWidth(width)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight)
    if special_text is not None:
        spin.setSpecialValueText(special_text)
    return spin


def _make_line(placeholder: str = "", *, min_width: int = 180, max_width: int | None = None) -> QLineEdit:
    line = QLineEdit()
    line.setPlaceholderText(placeholder)
    line.setMinimumWidth(min_width)
    if max_width is not None:
        line.setMaximumWidth(max_width)
    return line


def _compact_form_layout(parent=None) -> QFormLayout:
    form = QFormLayout(parent)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(6)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


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


class _DirtyMixin:
    def _mark_dirty(self, text: str):
        if getattr(self, "_loading", False):
            return
        self._dirty = True
        self._save_btn.setEnabled(True)
        self._status_lbl.setText(text)


class LocationsConverter(QWidget, _DirtyMixin):
    _auto_on_path = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._loading = False
        self._dirty = False
        self._locations = []
        self._original_locations = []
        self._index = -1
        self._fields = {}
        self._undo_stack = []
        self._redo_stack = []
        self._history_row = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)
        root.addWidget(_title("Locations Editor (DARKLAND.LOC)"))
        root.addWidget(_sep())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        list_panel = QWidget()
        list_lay = QVBoxLayout(list_panel)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(6)
        self._filter_edit = _make_line("Filter locations...", min_width=180)
        self._filter_edit.textChanged.connect(self._apply_filter)
        list_lay.addWidget(self._filter_edit)
        self._list = QListWidget()
        self._list.setMinimumWidth(230)
        self._list.setMaximumWidth(340)
        self._list.setFont(QFont("Courier New", 9))
        self._list.currentRowChanged.connect(self._on_select)
        list_lay.addWidget(self._list, stretch=1)
        splitter.addWidget(list_panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._form = _compact_form_layout(inner)
        self._form.setContentsMargins(12, 8, 12, 8)
        scroll.setWidget(inner)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 820])

        self._build_form()

        action = QHBoxLayout()
        self._status_lbl = QLabel("Set the DL path to load locations.")
        self._status_lbl.setStyleSheet("color: #777;")
        action.addWidget(self._status_lbl)
        action.addStretch()
        self._undo_hist_btn = QPushButton("Undo")
        self._undo_hist_btn.setEnabled(False)
        self._undo_hist_btn.clicked.connect(self._undo_history)
        action.addWidget(self._undo_hist_btn)
        self._redo_hist_btn = QPushButton("Redo")
        self._redo_hist_btn.setEnabled(False)
        self._redo_hist_btn.clicked.connect(self._redo_history)
        action.addWidget(self._redo_hist_btn)
        self._undo_btn = QPushButton("Revert Selected")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._undo_selected)
        action.addWidget(self._undo_btn)
        self._save_btn = QPushButton("Save DARKLAND.LOC")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        action.addWidget(self._save_btn)
        root.addLayout(action)

    def _build_form(self):
        icon_combo = QComboBox()
        for idx, name in enumerate(locTypes):
            icon_combo.addItem(f"{idx:02d}  {name}", idx)
        icon_combo.currentIndexChanged.connect(self._apply_form)
        self._fields["icon"] = icon_combo
        self._form.addRow("Icon:", icon_combo)

        def add_line(key, label):
            line = _make_line()
            line.textEdited.connect(self._apply_form)
            self._fields[key] = line
            self._form.addRow(label + ":", line)

        def add_spin(key, label, min_v, max_v):
            width = 76 if max_v <= 255 and min_v >= -255 else 92
            spin = _make_spin(min_v, max_v, width=width)
            spin.valueChanged.connect(self._apply_form)
            self._fields[key] = spin
            self._form.addRow(label + ":", spin)

        add_line("name", "Name")
        add_spin("coord_x", "Coord X", 0, 0xFFFF)
        add_spin("coord_y", "Coord Y", 0, 0xFFFF)
        add_spin("menu", "Menu", 0, 0xFFFF)
        add_spin("city_size", "City Size", 0, 255)
        add_spin("local_rep", "Local Rep", -32768, 32767)
        add_spin("inn_cache_idx", "Inn Cache Idx", -1, 0xFFFF)
        for key, label in (
            ("unknown1", "Unknown 1"),
            ("unknown2", "Unknown 2"),
            ("unknown3", "Unknown 3"),
            ("unknown4", "Unknown 4"),
            ("unknown5", "Unknown 5"),
            ("unknown6", "Unknown 6"),
            ("unknown9", "Unknown 9"),
        ):
            add_spin(key, label, 0, 0xFFFF)
        add_line("unknown7_c", "Unknown 7 (hex)")
        add_line("unknown8_c", "Unknown 8 (hex)")
        add_line("unknown10_c", "Unknown 10 (hex)")

    def set_dl_path(self, path: str):
        self.dl_path = path
        if path:
            self._load()

    def showEvent(self, event):
        super().showEvent(event)
        if self.dl_path and not self._locations:
            self._load()

    def _load(self):
        from vendor.darklands.reader_loc import readData

        self._locations = readData(self.dl_path)
        self._original_locations = copy.deepcopy(self._locations)
        self._list.clear()
        for i, loc in enumerate(self._locations):
            self._list.addItem(
                f"{i:03d}  {loc.get('name', ''):<20}  {loc.get('str_loc_type', '')}"
            )
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._undo_btn.setEnabled(False)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_row = None
        self._update_history_buttons()
        self._status_lbl.setText(f"Loaded {len(self._locations)} locations.")
        self._apply_filter()
        if self._locations:
            self._list.setCurrentRow(0)

    def focus_filter(self):
        self._filter_edit.setFocus()
        self._filter_edit.selectAll()

    def _apply_filter(self):
        needle = self._filter_edit.text().strip().lower()
        first_visible = -1
        for row in range(self._list.count()):
            item = self._list.item(row)
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = row
        current = self._list.currentRow()
        if current >= 0 and self._list.item(current).isHidden() and first_visible >= 0:
            self._list.setCurrentRow(first_visible)

    def _on_select(self, row: int):
        if row < 0 or row >= len(self._locations):
            return
        self._index = row
        self._history_row = None
        loc = self._locations[row]
        self._loading = True
        try:
            self._fields["icon"].setCurrentIndex(min(loc.get("icon", 0), self._fields["icon"].count() - 1))
            self._fields["name"].setText(loc.get("name", ""))
            x, y = loc.get("coords", (0, 0))
            self._fields["coord_x"].setValue(x)
            self._fields["coord_y"].setValue(y)
            self._fields["menu"].setValue(loc.get("menu", 0))
            self._fields["city_size"].setValue(loc.get("city_size", 0))
            self._fields["local_rep"].setValue(loc.get("local_rep", 0))
            inn_cache = loc.get("inn_cache_idx", 0xFFFF)
            self._fields["inn_cache_idx"].setValue(-1 if inn_cache == 0xFFFF else inn_cache)
            for key in ("unknown1", "unknown2", "unknown3", "unknown4", "unknown5", "unknown6", "unknown9"):
                self._fields[key].setValue(loc.get(key, 0))
            self._fields["unknown7_c"].setText(bytes(loc.get("unknown7_c", b"")).hex(" "))
            self._fields["unknown8_c"].setText(
                bytes(loc.get("unknown8_c", b"\x00\x00")).hex(" ")
                if isinstance(loc.get("unknown8_c"), (bytes, bytearray))
                else f"{int(loc.get('unknown8_c', 0)) & 0xFFFF:04x}"
            )
            self._fields["unknown10_c"].setText(bytes(loc.get("unknown10_c", b"")).hex(" "))
        finally:
            self._loading = False
        self._refresh_field_highlights()

    def _loc_unknown8_repr(self, value) -> str:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value[:2]).hex(" ")
        return f"{int(value) & 0xFFFF:04x}"

    def _refresh_field_highlights(self):
        if self._index < 0 or self._index >= len(self._locations):
            return
        loc = self._locations[self._index]
        orig = self._original_locations[self._index]
        _set_widget_edited(self._fields["icon"], loc.get("icon", 0) != orig.get("icon", 0))
        _set_widget_edited(self._fields["name"], loc.get("name", "") != orig.get("name", ""))
        _set_widget_edited(self._fields["coord_x"], loc.get("coords", (0, 0))[0] != orig.get("coords", (0, 0))[0])
        _set_widget_edited(self._fields["coord_y"], loc.get("coords", (0, 0))[1] != orig.get("coords", (0, 0))[1])
        _set_widget_edited(self._fields["menu"], loc.get("menu", 0) != orig.get("menu", 0))
        _set_widget_edited(self._fields["city_size"], loc.get("city_size", 0) != orig.get("city_size", 0))
        _set_widget_edited(self._fields["local_rep"], loc.get("local_rep", 0) != orig.get("local_rep", 0))
        _set_widget_edited(self._fields["inn_cache_idx"], loc.get("inn_cache_idx", 0xFFFF) != orig.get("inn_cache_idx", 0xFFFF))
        for key in ("unknown1", "unknown2", "unknown3", "unknown4", "unknown5", "unknown6", "unknown9"):
            _set_widget_edited(self._fields[key], loc.get(key, 0) != orig.get(key, 0))
        _set_widget_edited(self._fields["unknown7_c"], bytes(loc.get("unknown7_c", b"")) != bytes(orig.get("unknown7_c", b"")))
        _set_widget_edited(self._fields["unknown8_c"], self._loc_unknown8_repr(loc.get("unknown8_c", 0)) != self._loc_unknown8_repr(orig.get("unknown8_c", 0)))
        _set_widget_edited(self._fields["unknown10_c"], bytes(loc.get("unknown10_c", b"")) != bytes(orig.get("unknown10_c", b"")))
        self._undo_btn.setEnabled(loc != orig)

    def _update_dirty_state(self, text: str):
        self._dirty = self._locations != self._original_locations
        self._save_btn.setEnabled(self._dirty)
        self._status_lbl.setText(text if self._dirty else "No unsaved location changes.")
        self._refresh_field_highlights()
        self._refresh_list_item(self._index)

    def _changed_field_count(self, row: int) -> int:
        if row < 0 or row >= len(self._locations):
            return 0
        cur = self._locations[row]
        orig = self._original_locations[row]
        count = 0
        for key in ("icon", "name", "menu", "city_size", "local_rep", "inn_cache_idx", "unknown1", "unknown2", "unknown3", "unknown4", "unknown5", "unknown6", "unknown9"):
            count += int(cur.get(key) != orig.get(key))
        count += int(cur.get("coords", (0, 0))[0] != orig.get("coords", (0, 0))[0])
        count += int(cur.get("coords", (0, 0))[1] != orig.get("coords", (0, 0))[1])
        count += int(bytes(cur.get("unknown7_c", b"")) != bytes(orig.get("unknown7_c", b"")))
        count += int(self._loc_unknown8_repr(cur.get("unknown8_c", 0)) != self._loc_unknown8_repr(orig.get("unknown8_c", 0)))
        count += int(bytes(cur.get("unknown10_c", b"")) != bytes(orig.get("unknown10_c", b"")))
        return count

    def _refresh_list_item(self, row: int):
        if row < 0 or row >= len(self._locations):
            return
        item = self._list.item(row)
        if item is None:
            return
        loc = self._locations[row]
        dirty = self._changed_field_count(row)
        suffix = f"  *{dirty}" if dirty else ""
        item.setText(f"{row:03d}  {loc.get('name', ''):<20}  {loc.get('str_loc_type', '')}{suffix}")

    def _push_undo_state(self):
        row = self._index
        if row < 0 or row >= len(self._locations):
            return
        if self._history_row != row:
            self._undo_stack.append((row, copy.deepcopy(self._locations[row])))
            self._redo_stack.clear()
            self._history_row = row
            self._update_history_buttons()

    def _update_history_buttons(self):
        self._undo_hist_btn.setEnabled(bool(self._undo_stack))
        self._redo_hist_btn.setEnabled(bool(self._redo_stack))

    def _undo_history(self):
        if not self._undo_stack:
            return
        row, state = self._undo_stack.pop()
        current = copy.deepcopy(self._locations[row])
        self._redo_stack.append((row, current))
        self._locations[row] = copy.deepcopy(state)
        self._refresh_list_item(row)
        self._list.setCurrentRow(row)
        self._on_select(row)
        self._history_row = None
        self._update_history_buttons()
        self._update_dirty_state("Undid location edit.")

    def _redo_history(self):
        if not self._redo_stack:
            return
        row, state = self._redo_stack.pop()
        self._undo_stack.append((row, copy.deepcopy(self._locations[row])))
        self._locations[row] = copy.deepcopy(state)
        self._refresh_list_item(row)
        self._list.setCurrentRow(row)
        self._on_select(row)
        self._history_row = None
        self._update_history_buttons()
        self._update_dirty_state("Redid location edit.")

    def select_record(self, row: int):
        if 0 <= row < self._list.count():
            self._list.setCurrentRow(row)
            self._list.scrollToItem(self._list.item(row))

    def _apply_form(self, *_args):
        if self._loading or self._index < 0:
            return
        self._push_undo_state()
        loc = self._locations[self._index]
        loc["icon"] = self._fields["icon"].currentData()
        loc["str_loc_type"] = locTypes[loc["icon"]] if loc["icon"] < len(locTypes) else str(loc["icon"])
        loc["name"] = self._fields["name"].text()
        loc["coords"] = (self._fields["coord_x"].value(), self._fields["coord_y"].value())
        loc["menu"] = self._fields["menu"].value()
        loc["city_size"] = self._fields["city_size"].value()
        loc["local_rep"] = self._fields["local_rep"].value()
        loc["inn_cache_idx"] = 0xFFFF if self._fields["inn_cache_idx"].value() < 0 else self._fields["inn_cache_idx"].value()
        for key in ("unknown1", "unknown2", "unknown3", "unknown4", "unknown5", "unknown6", "unknown9"):
            loc[key] = self._fields[key].value()
        try:
            loc["unknown7_c"] = bytes.fromhex(self._fields["unknown7_c"].text().strip())[:3]
        except ValueError:
            pass
        try:
            u8 = self._fields["unknown8_c"].text().strip()
            loc["unknown8_c"] = bytes.fromhex(u8)[:2] if " " in u8 else int(u8 or "0", 16)
        except ValueError:
            pass
        try:
            loc["unknown10_c"] = bytes.fromhex(self._fields["unknown10_c"].text().strip())[:8]
        except ValueError:
            pass
        self._refresh_list_item(self._index)
        self._update_dirty_state("Location changes pending save.")

    def _undo_selected(self):
        if self._index < 0 or self._index >= len(self._locations):
            return
        self._locations[self._index] = copy.deepcopy(self._original_locations[self._index])
        self._refresh_list_item(self._index)
        self._on_select(self._index)
        self._history_row = None
        self._update_dirty_state("Reverted selected location.")

    def _save(self):
        from vendor.darklands.reader_loc import write_file

        path = os.path.join(self.dl_path, "DARKLAND.LOC")
        if not _confirm_validation(
            self,
            self.dl_path,
            ("LOC", "LOC/CTY"),
            {"locations": self._locations},
            "Validation Warning",
        ):
            return
        try:
            backup = backup_existing_file(path)
            write_file(path, self._locations)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        self._dirty = False
        self._original_locations = copy.deepcopy(self._locations)
        self._save_btn.setEnabled(False)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_row = None
        self._update_history_buttons()
        self._status_lbl.setText(f"Saved DARKLAND.LOC ({backup_label(backup)})")
        self._refresh_field_highlights()


class DescriptionsConverter(QWidget, _DirtyMixin):
    _auto_on_path = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._descs = []
        self._original_descs = []
        self._loading = False
        self._dirty = False
        self._undo_stack = []
        self._redo_stack = []
        self._history_row = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)
        root.addWidget(_title("Descriptions Editor (DARKLAND.DSC)"))
        root.addWidget(_sep())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        list_panel = QWidget()
        list_lay = QVBoxLayout(list_panel)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(6)
        self._filter_edit = _make_line("Filter descriptions...", min_width=180)
        self._filter_edit.textChanged.connect(self._apply_filter)
        list_lay.addWidget(self._filter_edit)
        self._list = QListWidget()
        self._list.setMinimumWidth(260)
        self._list.currentRowChanged.connect(self._on_select)
        list_lay.addWidget(self._list, stretch=1)
        splitter.addWidget(list_panel)

        self._text = QPlainTextEdit()
        self._text.textChanged.connect(self._apply_form)
        splitter.addWidget(self._text)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 800])

        action = QHBoxLayout()
        self._status_lbl = QLabel("Set the DL path to load descriptions.")
        self._status_lbl.setStyleSheet("color: #777;")
        action.addWidget(self._status_lbl)
        action.addStretch()
        self._undo_hist_btn = QPushButton("Undo")
        self._undo_hist_btn.setEnabled(False)
        self._undo_hist_btn.clicked.connect(self._undo_history)
        action.addWidget(self._undo_hist_btn)
        self._redo_hist_btn = QPushButton("Redo")
        self._redo_hist_btn.setEnabled(False)
        self._redo_hist_btn.clicked.connect(self._redo_history)
        action.addWidget(self._redo_hist_btn)
        self._undo_btn = QPushButton("Revert Selected")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._undo_selected)
        action.addWidget(self._undo_btn)
        self._save_btn = QPushButton("Save DARKLAND.DSC")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        action.addWidget(self._save_btn)
        root.addLayout(action)

    def set_dl_path(self, path: str):
        self.dl_path = path
        if path:
            self._load()

    def _load(self):
        from vendor.darklands.format_dsc import readData

        self._descs = readData(self.dl_path)
        self._original_descs = copy.deepcopy(self._descs)
        self._list.clear()
        for i, desc in enumerate(self._descs):
            self._list.addItem(f"{i:03d}  {desc[:40].replace(chr(10), ' ')}")
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._undo_btn.setEnabled(False)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_row = None
        self._update_history_buttons()
        self._status_lbl.setText(f"Loaded {len(self._descs)} descriptions.")
        self._apply_filter()
        if self._descs:
            self._list.setCurrentRow(0)

    def focus_filter(self):
        self._filter_edit.setFocus()
        self._filter_edit.selectAll()

    def _apply_filter(self):
        needle = self._filter_edit.text().strip().lower()
        first_visible = -1
        for row in range(self._list.count()):
            item = self._list.item(row)
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = row
        current = self._list.currentRow()
        if current >= 0 and self._list.item(current).isHidden() and first_visible >= 0:
            self._list.setCurrentRow(first_visible)

    def _on_select(self, row: int):
        if row < 0 or row >= len(self._descs):
            return
        self._history_row = None
        self._loading = True
        try:
            self._text.setPlainText(self._descs[row])
        finally:
            self._loading = False
        self._refresh_field_highlights()

    def _refresh_field_highlights(self):
        row = self._list.currentRow()
        edited = 0 <= row < len(self._descs) and self._descs[row] != self._original_descs[row]
        _set_widget_edited(self._text, edited)
        self._undo_btn.setEnabled(edited)

    def _update_dirty_state(self, text: str):
        self._dirty = self._descs != self._original_descs
        self._save_btn.setEnabled(self._dirty)
        self._status_lbl.setText(text if self._dirty else "No unsaved description changes.")
        self._refresh_field_highlights()
        row = self._list.currentRow()
        if row >= 0:
            self._refresh_list_item(row)

    def _refresh_list_item(self, row: int):
        if row < 0 or row >= len(self._descs):
            return
        item = self._list.item(row)
        if item is None:
            return
        dirty = self._descs[row] != self._original_descs[row]
        item.setText(f"{row:03d}  {self._descs[row][:40].replace(chr(10), ' ')}{'  *' if dirty else ''}")

    def _update_history_buttons(self):
        self._undo_hist_btn.setEnabled(bool(self._undo_stack))
        self._redo_hist_btn.setEnabled(bool(self._redo_stack))

    def _push_undo_state(self, row: int):
        if self._history_row != row:
            self._undo_stack.append((row, self._descs[row]))
            self._redo_stack.clear()
            self._history_row = row
            self._update_history_buttons()

    def _undo_history(self):
        if not self._undo_stack:
            return
        row, text = self._undo_stack.pop()
        current = self._descs[row]
        self._redo_stack.append((row, current))
        self._descs[row] = text
        self._list.setCurrentRow(row)
        self._on_select(row)
        self._history_row = None
        self._update_history_buttons()
        self._update_dirty_state("Undid description edit.")

    def _redo_history(self):
        if not self._redo_stack:
            return
        row, text = self._redo_stack.pop()
        self._undo_stack.append((row, self._descs[row]))
        self._descs[row] = text
        self._list.setCurrentRow(row)
        self._on_select(row)
        self._history_row = None
        self._update_history_buttons()
        self._update_dirty_state("Redid description edit.")

    def select_record(self, row: int):
        if 0 <= row < self._list.count():
            self._list.setCurrentRow(row)
            self._list.scrollToItem(self._list.item(row))

    def _apply_form(self):
        row = self._list.currentRow()
        if self._loading or row < 0:
            return
        self._push_undo_state(row)
        self._descs[row] = self._text.toPlainText()
        self._refresh_list_item(row)
        self._update_dirty_state("Description changes pending save.")

    def _undo_selected(self):
        row = self._list.currentRow()
        if row < 0:
            return
        self._descs[row] = self._original_descs[row]
        self._on_select(row)
        self._refresh_list_item(row)
        self._history_row = None
        self._update_dirty_state("Reverted selected description.")

    def _save(self):
        from vendor.darklands.format_dsc import write_file

        path = os.path.join(self.dl_path, "DARKLAND.DSC")
        if not _confirm_validation(
            self,
            self.dl_path,
            ("DSC", "CTY/DSC"),
            {"descs": self._descs},
            "Validation Warning",
        ):
            return
        try:
            backup = backup_existing_file(path)
            write_file(path, self._descs)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        self._dirty = False
        self._original_descs = copy.deepcopy(self._descs)
        self._save_btn.setEnabled(False)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_row = None
        self._update_history_buttons()
        self._status_lbl.setText(f"Saved DARKLAND.DSC ({backup_label(backup)})")
        self._refresh_field_highlights()


class CitiesConverter(QWidget, _DirtyMixin):
    _auto_on_path = True

    _STRING_FIELDS = [
        ("short_name", "Short Name"),
        ("name", "Full Name"),
        ("leader_name", "Leader Name"),
        ("ruler_name", "Ruler Name"),
        ("unknown", "Unknown Name 1"),
        ("center_name", "Political Center"),
        ("town_hall_name", "Town Hall"),
        ("fortress_name", "Fortress"),
        ("cathedral_name", "Cathedral"),
        ("church_name", "Church"),
        ("market_name", "Market"),
        ("unknown2", "Unknown Name 2"),
        ("slum_name", "Slum"),
        ("unknown3", "Unknown Name 3"),
        ("pawnshop_name", "Pawnshop"),
        ("kloster_name", "Kloster"),
        ("inn_name", "Inn"),
        ("university_name", "University"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._cities = []
        self._original_cities = []
        self._loading = False
        self._dirty = False
        self._index = -1
        self._fields = {}
        self._checks = {}
        self._undo_stack = []
        self._redo_stack = []
        self._history_row = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)
        root.addWidget(_title("Cities Editor (DARKLAND.CTY)"))
        root.addWidget(_sep())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        list_panel = QWidget()
        list_lay = QVBoxLayout(list_panel)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(6)
        self._filter_edit = _make_line("Filter cities...", min_width=180)
        self._filter_edit.textChanged.connect(self._apply_filter)
        list_lay.addWidget(self._filter_edit)
        self._list = QListWidget()
        self._list.setMinimumWidth(240)
        self._list.setMaximumWidth(340)
        self._list.currentRowChanged.connect(self._on_select)
        list_lay.addWidget(self._list, stretch=1)
        splitter.addWidget(list_panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(10, 8, 10, 8)
        self._layout.setSpacing(10)
        scroll.setWidget(inner)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 900])

        self._build_form()

        action = QHBoxLayout()
        self._status_lbl = QLabel("Set the DL path to load cities.")
        self._status_lbl.setStyleSheet("color: #777;")
        action.addWidget(self._status_lbl)
        action.addStretch()
        self._undo_hist_btn = QPushButton("Undo")
        self._undo_hist_btn.setEnabled(False)
        self._undo_hist_btn.clicked.connect(self._undo_history)
        action.addWidget(self._undo_hist_btn)
        self._redo_hist_btn = QPushButton("Redo")
        self._redo_hist_btn.setEnabled(False)
        self._redo_hist_btn.clicked.connect(self._redo_history)
        action.addWidget(self._redo_hist_btn)
        self._undo_btn = QPushButton("Revert Selected")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._undo_selected)
        action.addWidget(self._undo_btn)
        self._save_btn = QPushButton("Save DARKLAND.CTY")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        action.addWidget(self._save_btn)
        root.addLayout(action)

    def _build_form(self):
        basics = QGroupBox("Core Data")
        form = _compact_form_layout(basics)
        for key, label, min_v, max_v, width in (
            ("city_size", "City Size", 0, 0xFFFF, 92),
            ("entry_x", "Entry X", 0, 0xFFFF, 92),
            ("entry_y", "Entry Y", 0, 0xFFFF, 92),
            ("exit_x", "Exit X", 0, 0xFFFF, 92),
            ("exit_y", "Exit Y", 0, 0xFFFF, 92),
            ("coast", "Coast", 0, 0xFFFF, 92),
            ("unknown_cd_1", "Unknown 1", 0, 0xFFFF, 92),
            ("pseudo_ordinal", "Pseudo Ordinal", 0, 0xFFFF, 92),
            ("unknown_cd_2", "Unknown 2", 0, 0xFFFF, 92),
            ("unknown_cd_3", "Unknown 3", 0, 0xFFFF, 92),
            ("unknown_cd_4", "Unknown 4", 0, 0xFFFF, 92),
            ("qual_blacksmith", "Blacksmith", 0, 255, 76),
            ("qual_merchant", "Merchant", 0, 255, 76),
            ("qual_swordsmith", "Swordsmith", 0, 255, 76),
            ("qual_armorer", "Armorer", 0, 255, 76),
            ("qual_unk1", "Qual Unknown 1", 0, 255, 76),
            ("qual_bowyer", "Bowyer", 0, 255, 76),
            ("qual_tinker", "Tinker", 0, 255, 76),
            ("qual_unk2", "Qual Unknown 2", 0, 255, 76),
            ("qual_clothing", "Clothing", 0, 255, 76),
            ("qual_unk3", "Qual Unknown 3", 0, 255, 76),
            ("unknown_cd_5", "Unknown 5", 0, 255, 76),
            ("unknown_cd_6", "Unknown 6", 0, 255, 76),
        ):
            spin = _make_spin(min_v, max_v, width=width)
            spin.valueChanged.connect(self._apply_form)
            self._fields[key] = spin
            form.addRow(label + ":", spin)

        city_type = QComboBox()
        city_type.addItem("Free City", 0)
        city_type.addItem("Ruled City", 1)
        city_type.addItem("Capital", 2)
        city_type.setMinimumWidth(160)
        city_type.currentIndexChanged.connect(self._apply_form)
        self._fields["city_type"] = city_type
        form.addRow("City Type:", city_type)

        dock_row = QWidget()
        dock_lay = QHBoxLayout(dock_row)
        dock_lay.setContentsMargins(0, 0, 0, 0)
        dock_lay.setSpacing(6)
        for i in range(4):
            spin = _make_spin(-1, 0xFFFF, width=82, special_text="None")
            spin.valueChanged.connect(self._apply_form)
            self._fields[f"dock_{i}"] = spin
            dock_lay.addWidget(spin)
        dock_lay.addStretch()
        form.addRow("Docks:", dock_row)

        self._layout.addWidget(basics)

        flags = QGroupBox("City Contents")
        grid = QGridLayout(flags)
        for i, flag in enumerate(CITY_CONTENT_FLAGS):
            cb = QCheckBox(flag.replace("has_", "").replace("_", " "))
            cb.toggled.connect(self._apply_form)
            self._checks[flag] = cb
            grid.addWidget(cb, i // 2, i % 2)
        self._layout.addWidget(flags)

        names = QGroupBox("Names")
        names_form = _compact_form_layout(names)
        for key, label in self._STRING_FIELDS:
            line = _make_line(min_width=240)
            line.textEdited.connect(self._apply_form)
            self._fields[key] = line
            names_form.addRow(label + ":", line)
        self._layout.addWidget(names)
        self._layout.addStretch()

    def set_dl_path(self, path: str):
        self.dl_path = path
        if path:
            self._load()

    def _load(self):
        from vendor.darklands.format_cty import readData

        self._cities = readData(self.dl_path)
        self._original_cities = copy.deepcopy(self._cities)
        self._list.clear()
        for i, city in enumerate(self._cities):
            self._list.addItem(f"{i:03d}  {city.short_name or city.name}")
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._undo_btn.setEnabled(False)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_row = None
        self._update_history_buttons()
        self._status_lbl.setText(f"Loaded {len(self._cities)} cities.")
        self._apply_filter()
        if self._cities:
            self._list.setCurrentRow(0)

    def focus_filter(self):
        self._filter_edit.setFocus()
        self._filter_edit.selectAll()

    def _apply_filter(self):
        needle = self._filter_edit.text().strip().lower()
        first_visible = -1
        for row in range(self._list.count()):
            item = self._list.item(row)
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = row
        current = self._list.currentRow()
        if current >= 0 and self._list.item(current).isHidden() and first_visible >= 0:
            self._list.setCurrentRow(first_visible)

    def _on_select(self, row: int):
        if row < 0 or row >= len(self._cities):
            return
        self._index = row
        self._history_row = None
        city = self._cities[row]
        self._loading = True
        try:
            self._fields["city_size"].setValue(city.city_size)
            self._fields["entry_x"].setValue(city.entry_coords[0])
            self._fields["entry_y"].setValue(city.entry_coords[1])
            self._fields["exit_x"].setValue(city.exit_coords[0])
            self._fields["exit_y"].setValue(city.exit_coords[1])
            for key in (
                "coast", "unknown_cd_1", "pseudo_ordinal", "unknown_cd_2", "unknown_cd_3",
                "unknown_cd_4", "qual_blacksmith", "qual_merchant", "qual_swordsmith",
                "qual_armorer", "qual_unk1", "qual_bowyer", "qual_tinker", "qual_unk2",
                "qual_clothing", "qual_unk3", "unknown_cd_5", "unknown_cd_6",
            ):
                self._fields[key].setValue(getattr(city, key))
            self._fields["city_type"].setCurrentIndex(city.city_type)
            for i in range(4):
                self._fields[f"dock_{i}"].setValue(city.dock_destinations[i] if i < len(city.dock_destinations) else -1)
            for flag, cb in self._checks.items():
                cb.setChecked(bool(city.city_contents.get(flag)))
            for key, _label in self._STRING_FIELDS:
                self._fields[key].setText(getattr(city, key) or "")
        finally:
            self._loading = False
        self._refresh_field_highlights()

    def _refresh_field_highlights(self):
        if self._index < 0 or self._index >= len(self._cities):
            return
        city = self._cities[self._index]
        orig = self._original_cities[self._index]
        for key in (
            "city_size", "coast", "unknown_cd_1", "pseudo_ordinal", "unknown_cd_2", "unknown_cd_3",
            "unknown_cd_4", "qual_blacksmith", "qual_merchant", "qual_swordsmith", "qual_armorer",
            "qual_unk1", "qual_bowyer", "qual_tinker", "qual_unk2", "qual_clothing", "qual_unk3",
            "unknown_cd_5", "unknown_cd_6",
        ):
            _set_widget_edited(self._fields[key], getattr(city, key) != getattr(orig, key))
        _set_widget_edited(self._fields["entry_x"], city.entry_coords[0] != orig.entry_coords[0])
        _set_widget_edited(self._fields["entry_y"], city.entry_coords[1] != orig.entry_coords[1])
        _set_widget_edited(self._fields["exit_x"], city.exit_coords[0] != orig.exit_coords[0])
        _set_widget_edited(self._fields["exit_y"], city.exit_coords[1] != orig.exit_coords[1])
        _set_widget_edited(self._fields["city_type"], city.city_type != orig.city_type)
        for i in range(4):
            cur = city.dock_destinations[i] if i < len(city.dock_destinations) else -1
            old = orig.dock_destinations[i] if i < len(orig.dock_destinations) else -1
            _set_widget_edited(self._fields[f"dock_{i}"], cur != old)
        for flag, cb in self._checks.items():
            _set_widget_edited(cb, bool(city.city_contents.get(flag)) != bool(orig.city_contents.get(flag)))
        for key, _label in self._STRING_FIELDS:
            _set_widget_edited(self._fields[key], (getattr(city, key) or "") != (getattr(orig, key) or ""))
        self._undo_btn.setEnabled(city.__dict__ != orig.__dict__)

    def _update_dirty_state(self, text: str):
        self._dirty = any(city.__dict__ != orig.__dict__ for city, orig in zip(self._cities, self._original_cities))
        self._save_btn.setEnabled(self._dirty)
        self._status_lbl.setText(text if self._dirty else "No unsaved city changes.")
        self._refresh_field_highlights()
        self._refresh_list_item(self._index)

    def _changed_field_count(self, row: int) -> int:
        if row < 0 or row >= len(self._cities):
            return 0
        city = self._cities[row]
        orig = self._original_cities[row]
        count = 0
        count += int(city.city_size != orig.city_size)
        count += int(city.entry_coords != orig.entry_coords)
        count += int(city.exit_coords != orig.exit_coords)
        count += int(city.city_type != orig.city_type)
        count += int(city.dock_destinations != orig.dock_destinations)
        count += int(city.city_contents != orig.city_contents)
        for key in (
            "coast", "unknown_cd_1", "pseudo_ordinal", "unknown_cd_2", "unknown_cd_3",
            "unknown_cd_4", "qual_blacksmith", "qual_merchant", "qual_swordsmith",
            "qual_armorer", "qual_unk1", "qual_bowyer", "qual_tinker", "qual_unk2",
            "qual_clothing", "qual_unk3", "unknown_cd_5", "unknown_cd_6",
        ):
            count += int(getattr(city, key) != getattr(orig, key))
        for key, _label in self._STRING_FIELDS:
            count += int((getattr(city, key) or "") != (getattr(orig, key) or ""))
        return count

    def _refresh_list_item(self, row: int):
        if row < 0 or row >= len(self._cities):
            return
        item = self._list.item(row)
        if item is None:
            return
        city = self._cities[row]
        dirty = self._changed_field_count(row)
        item.setText(f"{row:03d}  {city.short_name or city.name}{f'  *{dirty}' if dirty else ''}")

    def _push_undo_state(self):
        row = self._index
        if row < 0 or row >= len(self._cities):
            return
        if self._history_row != row:
            self._undo_stack.append((row, copy.deepcopy(self._cities[row])))
            self._redo_stack.clear()
            self._history_row = row
            self._update_history_buttons()

    def _update_history_buttons(self):
        self._undo_hist_btn.setEnabled(bool(self._undo_stack))
        self._redo_hist_btn.setEnabled(bool(self._redo_stack))

    def _undo_history(self):
        if not self._undo_stack:
            return
        row, state = self._undo_stack.pop()
        self._redo_stack.append((row, copy.deepcopy(self._cities[row])))
        self._cities[row] = copy.deepcopy(state)
        self._refresh_list_item(row)
        self._list.setCurrentRow(row)
        self._on_select(row)
        self._history_row = None
        self._update_history_buttons()
        self._update_dirty_state("Undid city edit.")

    def _redo_history(self):
        if not self._redo_stack:
            return
        row, state = self._redo_stack.pop()
        self._undo_stack.append((row, copy.deepcopy(self._cities[row])))
        self._cities[row] = copy.deepcopy(state)
        self._refresh_list_item(row)
        self._list.setCurrentRow(row)
        self._on_select(row)
        self._history_row = None
        self._update_history_buttons()
        self._update_dirty_state("Redid city edit.")

    def select_record(self, row: int):
        if 0 <= row < self._list.count():
            self._list.setCurrentRow(row)
            self._list.scrollToItem(self._list.item(row))

    def _apply_form(self, *_args):
        if self._loading or self._index < 0:
            return
        self._push_undo_state()
        city = self._cities[self._index]
        city.city_size = self._fields["city_size"].value()
        city.entry_coords = (self._fields["entry_x"].value(), self._fields["entry_y"].value())
        city.exit_coords = (self._fields["exit_x"].value(), self._fields["exit_y"].value())
        for key in (
            "coast", "unknown_cd_1", "pseudo_ordinal", "unknown_cd_2", "unknown_cd_3",
            "unknown_cd_4", "qual_blacksmith", "qual_merchant", "qual_swordsmith",
            "qual_armorer", "qual_unk1", "qual_bowyer", "qual_tinker", "qual_unk2",
            "qual_clothing", "qual_unk3", "unknown_cd_5", "unknown_cd_6",
        ):
            setattr(city, key, self._fields[key].value())
        city.city_type = self._fields["city_type"].currentData()
        city.str_city_type = self._fields["city_type"].currentText()
        city.dock_destinations = [self._fields[f"dock_{i}"].value() for i in range(4) if self._fields[f"dock_{i}"].value() >= 0]
        city.city_contents = {flag: 1 if cb.isChecked() else 0 for flag, cb in self._checks.items()}
        for key, _label in self._STRING_FIELDS:
            setattr(city, key, self._fields[key].text())
        self._refresh_list_item(self._index)
        self._update_dirty_state("City changes pending save.")

    def _undo_selected(self):
        if self._index < 0 or self._index >= len(self._cities):
            return
        self._cities[self._index] = copy.deepcopy(self._original_cities[self._index])
        city = self._cities[self._index]
        self._refresh_list_item(self._index)
        self._on_select(self._index)
        self._history_row = None
        self._update_dirty_state("Reverted selected city.")

    def _save(self):
        from vendor.darklands.format_cty import write_file

        path = os.path.join(self.dl_path, "DARKLAND.CTY")
        if not _confirm_validation(
            self,
            self.dl_path,
            ("CTY", "CTY/DSC", "LOC/CTY"),
            {"cities": self._cities},
            "Validation Warning",
        ):
            return
        try:
            backup = backup_existing_file(path)
            write_file(path, self._cities)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        self._dirty = False
        self._original_cities = copy.deepcopy(self._cities)
        self._save_btn.setEnabled(False)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._history_row = None
        self._update_history_buttons()
        self._status_lbl.setText(f"Saved DARKLAND.CTY ({backup_label(backup)})")
        self._refresh_field_highlights()


class ItemsConverter(QWidget, _DirtyMixin):
    _auto_on_path = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._items = []
        self._saints = []
        self._formulae = []
        self._alchemy = []
        self._original_items = []
        self._original_saints = []
        self._original_formulae = []
        self._original_alchemy = []
        self._loading = False
        self._dirty = False
        self._item_combo_syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)
        root.addWidget(_title("Items, Saints, Formulae & Alchemy Editor (DARKLAND.LST / DARKLAND.SNT / DARKLAND.ALC)"))
        root.addWidget(_sep())

        self._filter_edit = _make_line("Filter current tab...", min_width=220)
        self._filter_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self._filter_edit)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)
        self._tabs.addTab(self._build_items_tab(), "Items")
        self._tabs.addTab(self._build_saints_tab(), "Saints")
        self._tabs.addTab(self._build_formulae_tab(), "Formulae")
        self._tabs.addTab(self._build_alchemy_tab(), "Alchemy")
        self._tabs.currentChanged.connect(lambda *_args: self._refresh_highlights())

        action = QHBoxLayout()
        self._status_lbl = QLabel("Set the DL path to load list data.")
        self._status_lbl.setStyleSheet("color: #777;")
        action.addWidget(self._status_lbl)
        action.addStretch()
        self._undo_btn = QPushButton("Revert Selected")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._undo_selected)
        action.addWidget(self._undo_btn)
        self._save_btn = QPushButton("Save DARKLAND.LST / DARKLAND.SNT / DARKLAND.ALC")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        action.addWidget(self._save_btn)
        root.addLayout(action)

    def _build_items_tab(self):
        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(["#", "Name", "Short", "Type", "Wt", "Q", "Value"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.itemChanged.connect(self._items_changed)
        table.currentCellChanged.connect(lambda *_args: self._refresh_highlights())
        self._items_table = table
        return table

    def _build_saints_tab(self):
        widget = QWidget()
        lay = QVBoxLayout(widget)
        self._saints_table = QTableWidget(0, 3)
        self._saints_table.setHorizontalHeaderLabels(["#", "Name", "Short"])
        self._saints_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._saints_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._saints_table.itemChanged.connect(self._saints_changed)
        self._saints_table.currentCellChanged.connect(self._on_saint_select)
        lay.addWidget(self._saints_table)
        lay.addWidget(QLabel("Description:"))
        self._saint_desc = QPlainTextEdit()
        self._saint_desc.textChanged.connect(self._saint_desc_changed)
        lay.addWidget(self._saint_desc, stretch=1)
        return widget

    def _build_formulae_tab(self):
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["#", "Name", "Short"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.itemChanged.connect(self._formula_changed)
        table.currentCellChanged.connect(lambda *_args: self._refresh_highlights())
        self._formula_table = table
        return table

    def _build_alchemy_tab(self):
        widget = QWidget()
        lay = QVBoxLayout(widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["#", "Formula", "Mystic", "Risk", "Ingredients"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.itemChanged.connect(self._alchemy_table_changed)
        table.currentCellChanged.connect(self._on_alchemy_select)
        self._alchemy_table = table
        lay.addWidget(table)

        detail = QGroupBox("Selected Formula")
        form = _compact_form_layout(detail)

        self._alchemy_formula_name = QLineEdit()
        self._alchemy_formula_name.setReadOnly(True)
        form.addRow("Formula:", self._alchemy_formula_name)

        self._alchemy_desc = QPlainTextEdit()
        self._alchemy_desc.setFixedHeight(82)
        self._alchemy_desc.textChanged.connect(self._alchemy_desc_changed)
        form.addRow("Description:", self._alchemy_desc)

        self._alchemy_mystic = _make_spin(0, 65535, width=96)
        self._alchemy_mystic.valueChanged.connect(self._alchemy_spin_changed)
        form.addRow("Mystic #:", self._alchemy_mystic)

        self._alchemy_risk = QComboBox()
        self._alchemy_risk.addItem("0 - Low", 0)
        self._alchemy_risk.addItem("1 - Medium", 1)
        self._alchemy_risk.addItem("2 - High", 2)
        self._alchemy_risk.currentIndexChanged.connect(self._alchemy_spin_changed)
        form.addRow("Risk:", self._alchemy_risk)

        ing_box = QGroupBox("Ingredients")
        ing_grid = QGridLayout(ing_box)
        ing_grid.addWidget(QLabel("Slot"), 0, 0)
        ing_grid.addWidget(QLabel("Qty"), 0, 1)
        ing_grid.addWidget(QLabel("Item"), 0, 2)
        self._alchemy_qty_spins = []
        self._alchemy_item_combos = []
        for slot in range(5):
            ing_grid.addWidget(QLabel(str(slot + 1)), slot + 1, 0)
            qty = _make_spin(0, 5, width=72, special_text="none")
            qty.valueChanged.connect(self._alchemy_ingredient_changed)
            combo = QComboBox()
            combo.setMinimumWidth(280)
            combo.currentIndexChanged.connect(self._alchemy_ingredient_changed)
            self._alchemy_qty_spins.append(qty)
            self._alchemy_item_combos.append(combo)
            ing_grid.addWidget(qty, slot + 1, 1)
            ing_grid.addWidget(combo, slot + 1, 2)
        form.addRow("", ing_box)

        lay.addWidget(detail)
        return widget

    def set_dl_path(self, path: str):
        self.dl_path = path
        if path:
            self._load()

    def _load(self):
        from vendor.darklands.reader_lst import readData
        from vendor.darklands.reader_alc import readData as readAlc

        self._items, self._saints, self._formulae = readData(self.dl_path)
        self._alchemy = readAlc(self.dl_path)
        self._original_items = copy.deepcopy(self._items)
        self._original_saints = copy.deepcopy(self._saints)
        self._original_formulae = copy.deepcopy(self._formulae)
        self._original_alchemy = copy.deepcopy(self._alchemy)
        self._loading = True
        try:
            self._populate_alchemy_item_choices()
            self._fill_items()
            self._fill_saints()
            self._fill_formulae()
            self._fill_alchemy()
        finally:
            self._loading = False
        self._dirty = False
        self._save_btn.setEnabled(False)
        self._undo_btn.setEnabled(False)
        self._status_lbl.setText(
            f"Loaded {len(self._items)} items, {len(self._saints)} saints, {len(self._formulae)} formulae, {len(self._alchemy)} alchemy definitions."
        )
        self._apply_filter()
        self._refresh_highlights()

    def focus_filter(self):
        self._filter_edit.setFocus()
        self._filter_edit.selectAll()

    def select_formula(self, row: int):
        if 0 <= row < self._formula_table.rowCount():
            self._tabs.setCurrentIndex(2)
            self._formula_table.setCurrentCell(row, 1)
            item = self._formula_table.item(row, 1) or self._formula_table.item(row, 0)
            if item is not None:
                self._formula_table.scrollToItem(item)

    def select_alchemy(self, row: int):
        if 0 <= row < self._alchemy_table.rowCount():
            self._tabs.setCurrentIndex(3)
            self._alchemy_table.setCurrentCell(row, 1)
            item = self._alchemy_table.item(row, 1) or self._alchemy_table.item(row, 0)
            if item is not None:
                self._alchemy_table.scrollToItem(item)

    def _fill_items(self):
        self._items_table.setRowCount(len(self._items))
        for r, item in enumerate(self._items):
            vals = [
                str(r),
                item.get("name", ""),
                item.get("short_name", ""),
                str(item.get("type", 0)),
                str(item.get("weight", 0)),
                str(item.get("quality", 0)),
                str(item.get("value", 0)),
            ]
            for c, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if c == 0:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._items_table.setItem(r, c, cell)
        if self._items:
            self._items_table.setCurrentCell(0, 1)

    def _fill_saints(self):
        self._saints_table.setRowCount(len(self._saints))
        for r, saint in enumerate(self._saints):
            for c, val in enumerate((str(r), saint.get("name", ""), saint.get("short_name", ""))):
                cell = QTableWidgetItem(val)
                if c == 0:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._saints_table.setItem(r, c, cell)
        if self._saints:
            self._saints_table.setCurrentCell(0, 1)

    def _fill_formulae(self):
        self._formula_table.setRowCount(len(self._formulae))
        for r, formula in enumerate(self._formulae):
            for c, val in enumerate((str(r), formula.get("name", ""), formula.get("short_name", ""))):
                cell = QTableWidgetItem(val)
                if c == 0:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._formula_table.setItem(r, c, cell)
        if self._formulae:
            self._formula_table.setCurrentCell(0, 1)

    def _fill_alchemy(self):
        self._alchemy_table.setRowCount(len(self._alchemy))
        for row in range(len(self._alchemy)):
            self._sync_alchemy_row(row)
        if self._alchemy:
            self._alchemy_table.setCurrentCell(0, 1)

    def _formula_display_name(self, row: int) -> str:
        if 0 <= row < len(self._formulae):
            return self._formulae[row].get("name", "")
        return f"Formula {row}"

    def _risk_label(self, risk: int) -> str:
        return {0: "Low", 1: "Medium", 2: "High"}.get(int(risk), str(risk))

    def _item_name_by_code(self, code: int) -> str:
        if 0 <= code < len(self._items):
            return self._items[code].get("name", f"Item {code}")
        return f"Item {code}"

    def _ingredient_summary(self, ingredients: list[dict]) -> str:
        parts = []
        for ing in ingredients[:5]:
            qty = int(ing.get("quantity", 0))
            code = int(ing.get("item_code", 0))
            if qty <= 0 and code == 0:
                continue
            parts.append(f"{qty}x {self._item_name_by_code(code)}")
        return ", ".join(parts) if parts else "(none)"

    def _sync_alchemy_row(self, row: int):
        if not (0 <= row < len(self._alchemy)):
            return
        formula = self._alchemy[row]
        values = [
            str(row),
            self._formula_display_name(row),
            str(formula.get("mystic_number", 0)),
            self._risk_label(int(formula.get("risk_factor", 0))),
            self._ingredient_summary(formula.get("ingredients", [])),
        ]
        for col, val in enumerate(values):
            cell = self._alchemy_table.item(row, col)
            if cell is None:
                cell = QTableWidgetItem()
                if col in (0, 1, 3, 4):
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._alchemy_table.setItem(row, col, cell)
            cell.setText(val)

    def _populate_alchemy_item_choices(self):
        self._item_combo_syncing = True
        try:
            current_codes = [combo.currentData() for combo in getattr(self, "_alchemy_item_combos", [])]
            for idx, combo in enumerate(getattr(self, "_alchemy_item_combos", [])):
                current = current_codes[idx] if idx < len(current_codes) else None
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("(none)", None)
                for item_idx, item in enumerate(self._items):
                    combo.addItem(f"{item_idx:03d} - {item.get('name', '')}", item_idx)
                if current is None:
                    combo.setCurrentIndex(0)
                else:
                    pos = combo.findData(current)
                    combo.setCurrentIndex(pos if pos >= 0 else 0)
                combo.blockSignals(False)
        finally:
            self._item_combo_syncing = False

    def _set_table_item_edited(self, item: QTableWidgetItem | None, edited: bool):
        if item is None:
            return
        item.setBackground(QColor(215, 170, 47, 45) if edited else Qt.GlobalColor.transparent)

    def _refresh_item_highlights(self):
        field_map = {1: "name", 2: "short_name", 3: "type", 4: "weight", 5: "quality", 6: "value"}
        for row in range(self._items_table.rowCount()):
            cur = self._items[row]
            orig = self._original_items[row]
            for col, key in field_map.items():
                self._set_table_item_edited(self._items_table.item(row, col), cur.get(key) != orig.get(key))

    def _refresh_saint_highlights(self):
        for row in range(self._saints_table.rowCount()):
            cur = self._saints[row]
            orig = self._original_saints[row]
            self._set_table_item_edited(self._saints_table.item(row, 1), cur.get("name", "") != orig.get("name", ""))
            self._set_table_item_edited(self._saints_table.item(row, 2), cur.get("short_name", "") != orig.get("short_name", ""))
        row = self._saints_table.currentRow()
        edited = 0 <= row < len(self._saints) and self._saints[row].get("description", "") != self._original_saints[row].get("description", "")
        _set_widget_edited(self._saint_desc, edited)

    def _refresh_formula_highlights(self):
        for row in range(self._formula_table.rowCount()):
            cur = self._formulae[row]
            orig = self._original_formulae[row]
            self._set_table_item_edited(self._formula_table.item(row, 1), cur.get("name", "") != orig.get("name", ""))
            self._set_table_item_edited(self._formula_table.item(row, 2), cur.get("short_name", "") != orig.get("short_name", ""))

    def _refresh_alchemy_highlights(self):
        for row in range(self._alchemy_table.rowCount()):
            cur = self._alchemy[row]
            orig = self._original_alchemy[row]
            cur_name = self._formulae[row].get("name", "") if row < len(self._formulae) else self._formula_display_name(row)
            orig_name = self._original_formulae[row].get("name", "") if row < len(self._original_formulae) else cur_name
            self._set_table_item_edited(self._alchemy_table.item(row, 1), cur_name != orig_name)
            self._set_table_item_edited(self._alchemy_table.item(row, 2), cur.get("mystic_number", 0) != orig.get("mystic_number", 0))
            self._set_table_item_edited(self._alchemy_table.item(row, 3), cur.get("risk_factor", 0) != orig.get("risk_factor", 0))
            edited = (
                cur.get("description", "") != orig.get("description", "")
                or cur.get("ingredients", []) != orig.get("ingredients", [])
            )
            self._set_table_item_edited(self._alchemy_table.item(row, 4), edited)
        row = self._alchemy_table.currentRow()
        if 0 <= row < len(self._alchemy):
            cur = self._alchemy[row]
            orig = self._original_alchemy[row]
            _set_widget_edited(self._alchemy_desc, cur.get("description", "") != orig.get("description", ""))
            _set_widget_edited(self._alchemy_mystic, cur.get("mystic_number", 0) != orig.get("mystic_number", 0))
            _set_widget_edited(self._alchemy_risk, cur.get("risk_factor", 0) != orig.get("risk_factor", 0))
            for slot, qty_spin in enumerate(self._alchemy_qty_spins):
                cur_ing = cur.get("ingredients", [])[slot]
                orig_ing = orig.get("ingredients", [])[slot]
                _set_widget_edited(qty_spin, int(cur_ing.get("quantity", 0)) != int(orig_ing.get("quantity", 0)))
                _set_widget_edited(
                    self._alchemy_item_combos[slot],
                    int(cur_ing.get("item_code", 0)) != int(orig_ing.get("item_code", 0)),
                )

    def _current_tab(self) -> int:
        return self._tabs.currentIndex()

    def _current_selection_changed(self) -> bool:
        tab = self._current_tab()
        if tab == 0:
            row = self._items_table.currentRow()
            return 0 <= row < len(self._items) and self._items[row] != self._original_items[row]
        if tab == 1:
            row = self._saints_table.currentRow()
            return 0 <= row < len(self._saints) and self._saints[row] != self._original_saints[row]
        if tab == 2:
            row = self._formula_table.currentRow()
            return 0 <= row < len(self._formulae) and self._formulae[row] != self._original_formulae[row]
        row = self._alchemy_table.currentRow()
        return 0 <= row < len(self._alchemy) and self._alchemy[row] != self._original_alchemy[row]

    def _refresh_highlights(self):
        was_loading = self._loading
        self._loading = True
        try:
            self._refresh_item_highlights()
            self._refresh_saint_highlights()
            self._refresh_formula_highlights()
            self._refresh_alchemy_highlights()
            self._undo_btn.setEnabled(self._current_selection_changed())
        finally:
            self._loading = was_loading

    def _update_dirty_state(self, text: str):
        self._dirty = (
            self._items != self._original_items
            or self._saints != self._original_saints
            or self._formulae != self._original_formulae
            or self._alchemy != self._original_alchemy
        )
        self._save_btn.setEnabled(self._dirty)
        self._status_lbl.setText(text if self._dirty else "No unsaved list changes.")
        self._refresh_highlights()

    def _apply_filter(self):
        needle = self._filter_edit.text().strip().lower()
        for row in range(self._items_table.rowCount()):
            hay = " ".join(
                self._items_table.item(row, col).text().lower()
                for col in range(1, self._items_table.columnCount())
                if self._items_table.item(row, col) is not None
            )
            self._items_table.setRowHidden(row, bool(needle) and needle not in hay)
        for row in range(self._saints_table.rowCount()):
            hay = " ".join(
                self._saints_table.item(row, col).text().lower()
                for col in range(1, self._saints_table.columnCount())
                if self._saints_table.item(row, col) is not None
            )
            desc = self._saints[row].get("description", "").lower() if row < len(self._saints) else ""
            self._saints_table.setRowHidden(row, bool(needle) and needle not in (hay + " " + desc))
        for row in range(self._formula_table.rowCount()):
            hay = " ".join(
                self._formula_table.item(row, col).text().lower()
                for col in range(1, self._formula_table.columnCount())
                if self._formula_table.item(row, col) is not None
            )
            self._formula_table.setRowHidden(row, bool(needle) and needle not in hay)
        for row in range(self._alchemy_table.rowCount()):
            parts = []
            for col in range(1, self._alchemy_table.columnCount()):
                item = self._alchemy_table.item(row, col)
                if item is not None:
                    parts.append(item.text().lower())
            desc = self._alchemy[row].get("description", "").lower() if row < len(self._alchemy) else ""
            self._alchemy_table.setRowHidden(row, bool(needle) and needle not in (" ".join(parts) + " " + desc))

    def _items_changed(self, item):
        if self._loading:
            return
        row, col = item.row(), item.column()
        fields = {1: "name", 2: "short_name", 3: "type", 4: "weight", 5: "quality", 6: "value"}
        key = fields.get(col)
        if key is None:
            return
        if key in {"type", "weight", "quality", "value"}:
            try:
                self._items[row][key] = int(item.text() or "0")
            except ValueError:
                return
        else:
            self._items[row][key] = item.text()
        self._populate_alchemy_item_choices()
        for alc_row in range(len(self._alchemy)):
            self._sync_alchemy_row(alc_row)
        self._update_dirty_state("Item changes pending save.")

    def _saints_changed(self, item):
        if self._loading:
            return
        row, col = item.row(), item.column()
        if col == 1:
            self._saints[row]["name"] = item.text()
        elif col == 2:
            self._saints[row]["short_name"] = item.text()
        else:
            return
        self._update_dirty_state("Saint changes pending save.")

    def _on_saint_select(self, row, _col, _prev_row, _prev_col):
        if row < 0 or row >= len(self._saints):
            return
        self._loading = True
        try:
            self._saint_desc.setPlainText(self._saints[row].get("description", ""))
        finally:
            self._loading = False
        self._refresh_highlights()

    def _saint_desc_changed(self):
        row = self._saints_table.currentRow()
        if self._loading or row < 0:
            return
        self._saints[row]["description"] = self._saint_desc.toPlainText()
        self._update_dirty_state("Saint description changes pending save.")

    def _formula_changed(self, item):
        if self._loading:
            return
        row, col = item.row(), item.column()
        if col == 1:
            self._formulae[row]["name"] = item.text()
        elif col == 2:
            self._formulae[row]["short_name"] = item.text()
        else:
            return
        self._sync_alchemy_row(row)
        self._update_dirty_state("Formula changes pending save.")

    def _alchemy_table_changed(self, item):
        if self._loading:
            return
        row, col = item.row(), item.column()
        if not (0 <= row < len(self._alchemy)):
            return
        if col == 2:
            try:
                self._alchemy[row]["mystic_number"] = int(item.text() or "0")
            except ValueError:
                return
            self._sync_alchemy_row(row)
            self._update_dirty_state("Alchemy changes pending save.")

    def _on_alchemy_select(self, row, _col, _prev_row, _prev_col):
        if row < 0 or row >= len(self._alchemy):
            return
        formula = self._alchemy[row]
        self._loading = True
        try:
            self._alchemy_formula_name.setText(self._formula_display_name(row))
            self._alchemy_desc.setPlainText(formula.get("description", ""))
            self._alchemy_mystic.setValue(int(formula.get("mystic_number", 0)))
            risk_idx = self._alchemy_risk.findData(int(formula.get("risk_factor", 0)))
            self._alchemy_risk.setCurrentIndex(risk_idx if risk_idx >= 0 else 0)
            for slot, ing in enumerate(formula.get("ingredients", [])[:5]):
                qty = int(ing.get("quantity", 0))
                code = int(ing.get("item_code", 0))
                self._alchemy_qty_spins[slot].setValue(qty)
                combo = self._alchemy_item_combos[slot]
                if qty == 0 and code == 0:
                    combo.setCurrentIndex(0)
                else:
                    pos = combo.findData(code)
                    combo.setCurrentIndex(pos if pos >= 0 else 0)
        finally:
            self._loading = False
        self._refresh_highlights()

    def _alchemy_desc_changed(self):
        row = self._alchemy_table.currentRow()
        if self._loading or row < 0:
            return
        self._alchemy[row]["description"] = self._alchemy_desc.toPlainText()
        self._sync_alchemy_row(row)
        self._update_dirty_state("Alchemy changes pending save.")

    def _alchemy_spin_changed(self):
        row = self._alchemy_table.currentRow()
        if self._loading or row < 0:
            return
        self._alchemy[row]["mystic_number"] = int(self._alchemy_mystic.value())
        self._alchemy[row]["risk_factor"] = int(self._alchemy_risk.currentData() or 0)
        self._sync_alchemy_row(row)
        self._update_dirty_state("Alchemy changes pending save.")

    def _alchemy_ingredient_changed(self):
        if self._loading or self._item_combo_syncing:
            return
        row = self._alchemy_table.currentRow()
        if row < 0:
            return
        ingredients = self._alchemy[row].get("ingredients", [])
        for slot in range(min(5, len(ingredients))):
            qty = int(self._alchemy_qty_spins[slot].value())
            code_data = self._alchemy_item_combos[slot].currentData()
            if qty <= 0 and code_data is None:
                ingredients[slot]["quantity"] = 0
                ingredients[slot]["item_code"] = 0
            else:
                ingredients[slot]["quantity"] = qty
                ingredients[slot]["item_code"] = int(code_data) if code_data is not None else 0
        self._sync_alchemy_row(row)
        self._update_dirty_state("Alchemy changes pending save.")

    def _undo_selected(self):
        tab = self._current_tab()
        if tab == 0:
            row = self._items_table.currentRow()
            if 0 <= row < len(self._items):
                self._items[row] = copy.deepcopy(self._original_items[row])
                self._loading = True
                try:
                    vals = [
                        str(row),
                        self._items[row].get("name", ""),
                        self._items[row].get("short_name", ""),
                        str(self._items[row].get("type", 0)),
                        str(self._items[row].get("weight", 0)),
                        str(self._items[row].get("quality", 0)),
                        str(self._items[row].get("value", 0)),
                    ]
                    for c, val in enumerate(vals):
                        cell = self._items_table.item(row, c)
                        if cell is not None:
                            cell.setText(val)
                finally:
                    self._loading = False
                self._update_dirty_state("Reverted selected item.")
        elif tab == 1:
            row = self._saints_table.currentRow()
            if 0 <= row < len(self._saints):
                self._saints[row] = copy.deepcopy(self._original_saints[row])
                self._loading = True
                try:
                    self._saints_table.item(row, 1).setText(self._saints[row].get("name", ""))
                    self._saints_table.item(row, 2).setText(self._saints[row].get("short_name", ""))
                    self._saint_desc.setPlainText(self._saints[row].get("description", ""))
                finally:
                    self._loading = False
                self._update_dirty_state("Reverted selected saint.")
        elif tab == 2:
            row = self._formula_table.currentRow()
            if 0 <= row < len(self._formulae):
                self._formulae[row] = copy.deepcopy(self._original_formulae[row])
                self._loading = True
                try:
                    self._formula_table.item(row, 1).setText(self._formulae[row].get("name", ""))
                    self._formula_table.item(row, 2).setText(self._formulae[row].get("short_name", ""))
                finally:
                    self._loading = False
                self._update_dirty_state("Reverted selected formula.")
        else:
            row = self._alchemy_table.currentRow()
            if 0 <= row < len(self._alchemy):
                self._alchemy[row] = copy.deepcopy(self._original_alchemy[row])
                self._loading = True
                try:
                    self._sync_alchemy_row(row)
                    self._alchemy_formula_name.setText(self._formula_display_name(row))
                    self._alchemy_desc.setPlainText(self._alchemy[row].get("description", ""))
                    self._alchemy_mystic.setValue(int(self._alchemy[row].get("mystic_number", 0)))
                    risk_idx = self._alchemy_risk.findData(int(self._alchemy[row].get("risk_factor", 0)))
                    self._alchemy_risk.setCurrentIndex(risk_idx if risk_idx >= 0 else 0)
                    for slot, ing in enumerate(self._alchemy[row].get("ingredients", [])[:5]):
                        self._alchemy_qty_spins[slot].setValue(int(ing.get("quantity", 0)))
                        combo = self._alchemy_item_combos[slot]
                        qty = int(ing.get("quantity", 0))
                        code = int(ing.get("item_code", 0))
                        if qty == 0 and code == 0:
                            combo.setCurrentIndex(0)
                        else:
                            pos = combo.findData(code)
                            combo.setCurrentIndex(pos if pos >= 0 else 0)
                finally:
                    self._loading = False
                self._update_dirty_state("Reverted selected alchemy formula.")

    def _save(self):
        from vendor.darklands.reader_lst import writeData
        from vendor.darklands.reader_alc import writeData as writeAlc

        if not _confirm_validation(
            self,
            self.dl_path,
            ("ENM/LST", "ALC", "ALC/LST"),
            {"items": self._items, "saints": self._saints, "formulae": self._formulae, "alchemy": self._alchemy},
            "Validation Warning",
        ):
            return
        try:
            lst_backup = backup_existing_file(os.path.join(self.dl_path, "DARKLAND.LST"))
            snt_backup = backup_existing_file(os.path.join(self.dl_path, "DARKLAND.SNT"))
            alc_backup = backup_existing_file(os.path.join(self.dl_path, "DARKLAND.ALC"))
            writeData(self.dl_path, self._items, self._saints, self._formulae)
            writeAlc(self.dl_path, self._alchemy)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return
        self._dirty = False
        self._original_items = copy.deepcopy(self._items)
        self._original_saints = copy.deepcopy(self._saints)
        self._original_formulae = copy.deepcopy(self._formulae)
        self._original_alchemy = copy.deepcopy(self._alchemy)
        self._save_btn.setEnabled(False)
        self._status_lbl.setText(
            f"Saved DARKLAND.LST, DARKLAND.SNT and DARKLAND.ALC ({backup_label(lst_backup)}, {backup_label(snt_backup)}, {backup_label(alc_backup)})"
        )
        self._refresh_highlights()
