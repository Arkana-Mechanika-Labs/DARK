"""
Text converters: dialog cards (MSG files) and descriptions (DSC).
"""
import copy
import io
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .base import TextConverter
from app.file_ops import backup_existing_file, backup_label
from app.validation import summarize_issues, validate_msg_cards

_OPTION_KINDS = {"STD", "PTN", "SNT", "BTL"}
_VAR_RE = re.compile(r"\$[A-Za-z][A-Za-z0-9_]*")


def _set_validation_label(label: QLabel, issues: list):
    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    if errors:
        label.setText(f"Validation: {errors} error(s), {warnings} warning(s)")
        label.setStyleSheet("color: #c75050; font-weight: bold;")
    elif warnings:
        label.setText(f"Validation: {warnings} warning(s)")
        label.setStyleSheet("color: #c28a2c;")
    else:
        label.setText("Validation: clean")
        label.setStyleSheet("color: #5d996c;")


def _show_issue_details(parent, title: str, issues: list):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning if issues else QMessageBox.Icon.Information)
    if issues:
        box.setText(f"{len(issues)} validation issue(s) in this editor scope.")
        box.setDetailedText(summarize_issues(issues, max_lines=32))
    else:
        box.setText("No validation issues in this editor scope.")
    box.exec()


class DescriptionsConverter(TextConverter):
    def __init__(self, parent=None):
        super().__init__("Descriptions (DARKLAND.DSC)", parent)

    def run(self):
        if self._need_dl_path():
            return
        from darklands.format_dsc import readData
        descs = readData(self.dl_path)
        buf = io.StringIO()
        buf.write(f"=== Descriptions ({len(descs)}) ===\n\n")
        for i, d in enumerate(descs):
            if d:
                buf.write(f"{i:4d}: {d}\n")
        self._show_text(buf.getvalue())


class DialogsConverter(QWidget):
    """Structured editor for Darklands .MSG dialog-card files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._cards = []
        self._current_file = ""
        self._current_catalog = ""
        self._current_entry_name = ""
        self._current_card_idx = -1
        self._loading = False
        self._dirty = False
        self._original_cards = []
        self._msgfiles_archive = None
        self._current_msgfiles_entry = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        title = QLabel("Dialog Cards Editor (*.MSG)")
        tf = title.font()
        tf.setPointSize(11)
        tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_file_panel())
        splitter.addWidget(self._build_card_panel())
        splitter.addWidget(self._build_editor_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([220, 240, 760])

        action_row = QHBoxLayout()
        self._status = QLabel("")
        self._status.setStyleSheet("color: #666; font-style: italic;")
        action_row.addWidget(self._status)
        self._validation_lbl = QLabel("")
        self._validation_lbl.setStyleSheet("color: #777;")
        action_row.addWidget(self._validation_lbl)
        self._issues_btn = QPushButton("Issues...")
        self._issues_btn.clicked.connect(self._show_validation_details)
        action_row.addWidget(self._issues_btn)
        action_row.addStretch()

        copy_btn = QPushButton("Copy Preview")
        copy_btn.clicked.connect(self._copy_preview)
        action_row.addWidget(copy_btn)

        export_btn = QPushButton("Export TXT...")
        export_btn.clicked.connect(self._save_txt)
        action_row.addWidget(export_btn)

        self._save_btn = QPushButton("Save MSG")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_file)
        action_row.addWidget(self._save_btn)

        root.addLayout(action_row)

    def _build_file_panel(self):
        left = QWidget()
        left.setMinimumWidth(170)
        left.setMaximumWidth(280)
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder...")
        self.folder_edit.setReadOnly(True)
        row.addWidget(self.folder_edit)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(28)
        browse_btn.clicked.connect(self._browse_folder)
        row.addWidget(browse_btn)
        lay.addLayout(row)

        self._file_filter = QLineEdit()
        self._file_filter.setPlaceholderText("Filter MSG files...")
        self._file_filter.textChanged.connect(self._apply_file_filter)
        lay.addWidget(self._file_filter)

        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self._on_file_clicked)
        lay.addWidget(self.file_list)

        meta_hdr = QLabel("Selected file info")
        meta_hdr.setStyleSheet("font-weight: bold; color: #555;")
        lay.addWidget(meta_hdr)

        self._file_info = QPlainTextEdit()
        self._file_info.setReadOnly(True)
        self._file_info.setMaximumHeight(150)
        self._file_info.setFont(QFont("Courier New", 8))
        self._file_info.setPlainText("Select a directory or MSGFILES-backed message to inspect its catalog metadata.")
        lay.addWidget(self._file_info)
        return left

    def _build_card_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(180)
        panel.setMaximumWidth(320)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(4)

        hdr = QLabel("Cards")
        hdr.setStyleSheet("font-weight: bold; color: #555;")
        lay.addWidget(hdr)

        self.card_list = QListWidget()
        self.card_list.setFont(QFont("Courier New", 8))
        self.card_list.currentRowChanged.connect(self._on_card_selected)
        lay.addWidget(self.card_list, stretch=1)

        row = QHBoxLayout()
        add_card = QPushButton("+ Card")
        add_card.clicked.connect(self._add_card)
        row.addWidget(add_card)
        del_card = QPushButton("- Card")
        del_card.clicked.connect(self._remove_card)
        row.addWidget(del_card)
        up_card = QPushButton("Up")
        up_card.clicked.connect(lambda: self._move_card(-1))
        row.addWidget(up_card)
        down_card = QPushButton("Down")
        down_card.clicked.connect(lambda: self._move_card(1))
        row.addWidget(down_card)
        row.addStretch()
        lay.addLayout(row)

        row = QHBoxLayout()
        add_text = QPushButton("+ Text")
        add_text.clicked.connect(lambda: self._add_row("TEXT"))
        row.addWidget(add_text)
        add_opt = QPushButton("+ Option")
        add_opt.clicked.connect(lambda: self._add_row("STD"))
        row.addWidget(add_opt)
        row.addStretch()
        lay.addLayout(row)
        return panel

    def _build_editor_panel(self):
        right = QWidget()
        lay = QVBoxLayout(right)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(6)

        self.editor_title = QLabel("Select a .MSG file and card")
        ef = self.editor_title.font()
        ef.setPointSize(10)
        ef.setBold(True)
        self.editor_title.setFont(ef)
        lay.addWidget(self.editor_title)

        header_row = QHBoxLayout()
        self.text_offs_y = self._spin(header_row, "Y", 0, 255)
        self.text_offs_x = self._spin(header_row, "X", 0, 255)
        self.unknown1 = self._spin(header_row, "Unk1", 0, 255)
        self.text_max_x = self._spin(header_row, "Max X", 0, 255)
        self.unknown2 = self._spin(header_row, "Unk2", 0, 255)
        header_row.addStretch()
        lay.addLayout(header_row)

        row_hdr = QLabel("Elements")
        row_hdr.setStyleSheet("font-weight: bold; color: #555;")
        lay.addWidget(row_hdr)

        self.elem_table = QTableWidget(0, 3)
        self.elem_table.setHorizontalHeaderLabels(["Type", "Dots / Text", "Label"])
        self.elem_table.verticalHeader().setVisible(False)
        self.elem_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.elem_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.elem_table.itemChanged.connect(self._on_table_changed)
        self.elem_table.horizontalHeader().setStretchLastSection(True)
        self.elem_table.setColumnWidth(0, 80)
        self.elem_table.setColumnWidth(1, 240)
        lay.addWidget(self.elem_table, stretch=1)

        row_actions = QHBoxLayout()
        remove_btn = QPushButton("Remove Row")
        remove_btn.clicked.connect(self._remove_row)
        row_actions.addWidget(remove_btn)
        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(lambda: self._move_row(-1))
        row_actions.addWidget(up_btn)
        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(lambda: self._move_row(1))
        row_actions.addWidget(down_btn)
        row_actions.addStretch()
        lay.addLayout(row_actions)

        preview_hdr = QLabel("Rendered Preview")
        preview_hdr.setStyleSheet("font-weight: bold; color: #555;")
        lay.addWidget(preview_hdr)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Courier New", 9))
        self.preview.setMaximumHeight(210)
        lay.addWidget(self.preview)

        self.vars_label = QLabel("")
        self.vars_label.setWordWrap(True)
        self.vars_label.setStyleSheet("color: #666; font-size: 8pt;")
        lay.addWidget(self.vars_label)

        return right

    def _spin(self, layout, label, lo, hi):
        layout.addWidget(QLabel(label + ":"))
        sb = QSpinBox()
        sb.setRange(lo, hi)
        sb.setFixedWidth(64)
        sb.valueChanged.connect(self._on_header_changed)
        layout.addWidget(sb)
        return sb

    def set_dl_path(self, path: str):
        self.dl_path = path
        self.folder_edit.setText(path)
        self._refresh_list(path)

    def open_file(self, fpath: str):
        if not fpath or not os.path.isfile(fpath):
            return False
        folder = os.path.dirname(fpath)
        self.folder_edit.setText(folder)
        self._refresh_list(folder)
        base = os.path.basename(fpath)
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            payload = item.data(Qt.ItemDataRole.UserRole) if item else None
            if payload and payload[0] == "file" and str(payload[2]).upper() == base.upper():
                self.file_list.setCurrentRow(row)
                self._on_file_clicked(item)
                return True
        self._load_file(fpath)
        return True

    def focus_filter(self):
        self._file_filter.setFocus()
        self._file_filter.selectAll()

    def select_card(self, row: int):
        if 0 <= row < self.card_list.count():
            self.card_list.setCurrentRow(row)
            self.card_list.scrollToItem(self.card_list.item(row))

    def open_message(self, msg_name: str):
        if not msg_name:
            return False
        upper_name = msg_name.upper()
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            payload = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not payload:
                continue
            kind, path, name = payload
            if str(name).upper() != upper_name:
                continue
            self.file_list.setCurrentRow(row)
            self._on_file_clicked(item)
            return True
        if self.dl_path:
            cat_path = os.path.join(self.dl_path, "MSGFILES")
            if os.path.isfile(cat_path):
                return self.open_catalog_entry(cat_path, msg_name)
            loose = os.path.join(self.dl_path, msg_name)
            if os.path.isfile(loose):
                return self.open_file(loose)
        return False

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select MSG Folder", self.folder_edit.text() or self.dl_path or ""
        )
        if path:
            self.folder_edit.setText(path)
            self._refresh_list(path)

    def _refresh_list(self, folder: str):
        self.file_list.clear()
        self.card_list.clear()
        self._cards = []
        self._current_file = ""
        self._current_catalog = ""
        self._current_entry_name = ""
        self._current_card_idx = -1
        if not folder or not os.path.isdir(folder):
            return
        msgfiles_path = os.path.join(folder, "MSGFILES")
        self._msgfiles_archive = None
        if os.path.isfile(msgfiles_path):
            try:
                from darklands.reader_msgfiles import readData as read_msgfiles
                from darklands.extract_cat import readEntries
                self._msgfiles_archive = read_msgfiles(msgfiles_path)
                entries = sorted(
                    (entry['name'] for entry in readEntries(msgfiles_path)
                     if entry['name'].upper().endswith('.MSG')),
                    key=str.upper,
                )
                for fname in entries:
                    item = QListWidgetItem(f"[MSGFILES] {fname}")
                    item.setData(Qt.ItemDataRole.UserRole, ("catalog", msgfiles_path, fname))
                    self.file_list.addItem(item)
            except Exception:
                pass
        files = sorted(f for f in os.listdir(folder) if f.upper().endswith(".MSG"))
        for fname in files:
            item = QListWidgetItem(f"[DIR] {fname}")
            item.setData(Qt.ItemDataRole.UserRole, ("file", os.path.join(folder, fname), fname))
            self.file_list.addItem(item)
        self._apply_file_filter()

    def _apply_file_filter(self):
        needle = self._file_filter.text().strip().lower()
        first_visible = -1
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = row
        current = self.file_list.currentRow()
        if current >= 0 and self.file_list.item(current).isHidden() and first_visible >= 0:
            self.file_list.setCurrentRow(first_visible)

    def _on_file_clicked(self, item: QListWidgetItem):
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not payload:
            return
        kind, path, name = payload
        if kind == "catalog":
            self._load_catalog_entry(path, name)
        else:
            self._load_file(path)

    def _set_file_info(self, text: str):
        self._file_info.setPlainText(text)

    def _refresh_validation_badge(self):
        if not self._cards:
            self._validation_lbl.setText("")
            self._issues_btn.setEnabled(False)
            return
        issues = self._validation_issues()
        _set_validation_label(self._validation_lbl, issues)
        self._issues_btn.setEnabled(True)

    def _validation_issues(self):
        msg_name = self._current_entry_name or os.path.basename(self._current_file) or "<MSG>"
        msgfiles_names = []
        if self._msgfiles_archive is not None:
            msgfiles_names = [entry.filename for entry in self._msgfiles_archive.entries]
        return validate_msg_cards(self._cards, msg_name, msgfiles_names).issues

    def _show_validation_details(self):
        _show_issue_details(self, "Dialog Validation", self._validation_issues())

    def _card_issue_counts(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for issue in self._validation_issues():
            match = re.search(r"card\s+#(\d+)", getattr(issue, "message", ""), re.IGNORECASE)
            if not match:
                continue
            idx = int(match.group(1))
            counts[idx] = counts.get(idx, 0) + 1
        return counts

    def _describe_msgfiles_entry(self, entry) -> str:
        if entry is None or self._msgfiles_archive is None:
            return "MSGFILES entry metadata unavailable."
        lines = [
            "Source: MSGFILES archive",
            f"Archive: {os.path.basename(self._msgfiles_archive.path)}",
            f"Entries: {len(self._msgfiles_archive.entries)}",
            f"First payload offset: 0x{self._msgfiles_archive.first_payload_offset:04X} ({self._msgfiles_archive.first_payload_offset})",
            "",
            f"Index: {entry.index}",
            f"Filename: {entry.filename}",
            f"Raw field @0x0C: 0x{entry.raw_field_0c:08X} ({entry.raw_field_0c})",
            f"Size: {entry.size} bytes",
            f"Offset: 0x{entry.offset:08X} ({entry.offset})",
        ]
        problems = self._msgfiles_archive.validate()
        if problems:
            lines.extend(["", "Archive checks:"] + [f"- {problem}" for problem in problems[:4]])
        else:
            lines.extend(["", "Archive checks:", "- contiguous payload layout OK"])
        return "\n".join(lines)

    def _describe_directory_file(self, path: str) -> str:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        return "\n".join([
            "Source: directory file",
            f"Path: {path}",
            f"Size: {size} bytes",
        ])

    def _load_file(self, fpath: str):
        from darklands.reader_msg import readData

        self._cards = readData(fpath)
        self._current_file = fpath
        self._current_catalog = ""
        self._current_entry_name = ""
        self._current_msgfiles_entry = None
        self._current_card_idx = -1
        self._dirty = False
        self._original_cards = copy.deepcopy(self._cards)
        self._save_btn.setEnabled(False)
        self._status.setText(f"Loaded {os.path.basename(fpath)}")
        self.editor_title.setText(os.path.basename(fpath))
        self._set_file_info(self._describe_directory_file(fpath))
        self._refresh_validation_badge()
        self._rebuild_card_list()
        self._clear_editor()
        if self._cards:
            self.card_list.setCurrentRow(0)

    def _load_catalog_entry(self, cat_path: str, entry_name: str):
        from darklands.extract_cat import readEntries
        from darklands.reader_msg import readDataBytes

        for entry in readEntries(cat_path):
            if entry['name'].upper() == entry_name.upper():
                self._cards = readDataBytes(entry.get('data', b''))
                self._current_file = ""
                self._current_catalog = cat_path
                self._current_entry_name = entry['name']
                self._current_msgfiles_entry = (
                    self._msgfiles_archive.get(entry['name']) if self._msgfiles_archive else None
                )
                self._current_card_idx = -1
                self._dirty = False
                self._original_cards = copy.deepcopy(self._cards)
                self._save_btn.setEnabled(False)
                self._status.setText(
                    f"Loaded {entry['name']} from {os.path.basename(cat_path)}"
                )
                self.editor_title.setText(f"{entry['name']}  [{os.path.basename(cat_path)}]")
                self._set_file_info(self._describe_msgfiles_entry(self._current_msgfiles_entry))
                self._refresh_validation_badge()
                self._rebuild_card_list()
                self._clear_editor()
                if self._cards:
                    self.card_list.setCurrentRow(0)
                return

    def open_catalog_entry(self, cat_path: str, entry_name: str, data: bytes | None = None):
        folder = os.path.dirname(cat_path)
        self.folder_edit.setText(folder)
        self._refresh_list(folder)
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            payload = item.data(Qt.ItemDataRole.UserRole) if item else None
            if payload and payload[0] == "catalog" and str(payload[1]).upper() == cat_path.upper() and str(payload[2]).upper() == entry_name.upper():
                self.file_list.setCurrentRow(row)
                self._on_file_clicked(item)
                return True
        if data is None:
            return False
        try:
            from darklands.reader_msg import readDataBytes
            self._cards = readDataBytes(data)
            self._current_file = ""
            self._current_catalog = cat_path
            self._current_entry_name = entry_name
            self._current_msgfiles_entry = (
                self._msgfiles_archive.get(entry_name) if self._msgfiles_archive else None
            )
            self._current_card_idx = -1
            self._dirty = False
            self._original_cards = copy.deepcopy(self._cards)
            self._save_btn.setEnabled(False)
            self._status.setText(f"Loaded {entry_name} from {os.path.basename(cat_path)}")
            self.editor_title.setText(f"{entry_name}  [{os.path.basename(cat_path)}]")
            self._set_file_info(self._describe_msgfiles_entry(self._current_msgfiles_entry))
            self._refresh_validation_badge()
            self._rebuild_card_list()
            self._clear_editor()
            if self._cards:
                self.card_list.setCurrentRow(0)
            return True
        except Exception:
            return False

    def _clear_editor(self):
        self._loading = True
        for widget in (self.text_offs_y, self.text_offs_x, self.unknown1, self.text_max_x, self.unknown2):
            widget.setValue(0)
        self.elem_table.setRowCount(0)
        self.preview.clear()
        self.vars_label.clear()
        self._loading = False

    def _rebuild_card_list(self):
        self.card_list.blockSignals(True)
        current = self._current_card_idx
        self.card_list.clear()
        issue_counts = self._card_issue_counts()
        for idx, card in enumerate(self._cards):
            preview = self._card_summary(card)
            dirty = idx >= len(self._original_cards) or card != self._original_cards[idx]
            issue_marker = f"  !{issue_counts[idx]}" if idx in issue_counts else ""
            self.card_list.addItem(f"{idx:02d}  {preview}{issue_marker}{'  *' if dirty else ''}")
        if 0 <= current < self.card_list.count():
            self.card_list.setCurrentRow(current)
        self.card_list.blockSignals(False)

    def _card_summary(self, card):
        for element in card.get("elements", []):
            if isinstance(element, str) and element.strip():
                return element[:36]
            if isinstance(element, (list, tuple)) and element:
                kind = str(element[0]).upper()
                label = ""
                if len(element) > 2 and element[2]:
                    label = element[2]
                elif len(element) > 1 and element[1]:
                    label = element[1]
                if label:
                    return f"[{kind}] {label[:28]}"
                return f"[{kind}]"
        return "(empty card)"

    def _on_card_selected(self, row: int):
        self._flush_current_card()
        self._current_card_idx = row
        if row < 0 or row >= len(self._cards):
            self._clear_editor()
            return
        self._populate_card(row)

    def _populate_card(self, row: int):
        card = self._cards[row]
        self._loading = True
        self.text_offs_y.setValue(int(card.get("textOffsY", 0)))
        self.text_offs_x.setValue(int(card.get("textOffsX", 0)))
        self.unknown1.setValue(int(card.get("unknown1", 0)))
        self.text_max_x.setValue(int(card.get("textMaxX", 0)))
        self.unknown2.setValue(int(card.get("unknown2", 0)))
        self.elem_table.setRowCount(0)
        for element in card.get("elements", []):
            self._insert_element_row(element)
        self._loading = False
        self._render_preview()

    def _insert_element_row(self, element):
        row = self.elem_table.rowCount()
        self.elem_table.insertRow(row)
        if isinstance(element, str):
            values = ["TEXT", element, ""]
        else:
            kind = str(element[0]).upper() if element else "TEXT"
            dots = element[1] if len(element) > 1 else ""
            label = element[2] if len(element) > 2 else ""
            values = [kind, dots, label]
        for col, value in enumerate(values):
            self.elem_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _collect_elements(self):
        elements = []
        for row in range(self.elem_table.rowCount()):
            kind_item = self.elem_table.item(row, 0)
            dots_item = self.elem_table.item(row, 1)
            label_item = self.elem_table.item(row, 2)
            kind = (kind_item.text().strip().upper() if kind_item else "TEXT") or "TEXT"
            dots = dots_item.text() if dots_item else ""
            label = label_item.text() if label_item else ""
            if kind == "TEXT":
                if dots.strip():
                    elements.append(dots)
            elif kind in _OPTION_KINDS:
                entry = [kind]
                if dots:
                    entry.append(dots)
                if label:
                    while len(entry) < 2:
                        entry.append("")
                    entry.append(label)
                elements.append(entry)
        return elements

    def _flush_current_card(self):
        if self._loading:
            return
        row = self._current_card_idx
        if row < 0 or row >= len(self._cards):
            return
        card = self._cards[row]
        card["textOffsY"] = self.text_offs_y.value()
        card["textOffsX"] = self.text_offs_x.value()
        card["unknown1"] = self.unknown1.value()
        card["textMaxX"] = self.text_max_x.value()
        card["unknown2"] = self.unknown2.value()
        card["elements"] = self._collect_elements()
        card["text"] = self._preview_text(card["elements"])
        self._rebuild_card_label(row)
        self._render_preview()

    def _rebuild_card_label(self, row):
        item = self.card_list.item(row)
        if item is not None:
            dirty = row >= len(self._original_cards) or self._cards[row] != self._original_cards[row]
            issue_count = self._card_issue_counts().get(row, 0)
            issue_marker = f"  !{issue_count}" if issue_count else ""
            item.setText(f"{row:02d}  {self._card_summary(self._cards[row])}{issue_marker}{'  *' if dirty else ''}")

    def _render_preview(self):
        if self._current_card_idx < 0 or self._current_card_idx >= len(self._cards):
            self.preview.clear()
            self.vars_label.clear()
            return
        rendered = self._preview_text(self._cards[self._current_card_idx].get("elements", []))
        self.preview.setPlainText(rendered)
        vars_found = sorted(set(_VAR_RE.findall(rendered)))
        if vars_found:
            self.vars_label.setText(
                "Variables / card references: " + ", ".join(vars_found)
            )
        else:
            self.vars_label.setText("Variables / card references: none in this card")

    def _preview_text(self, elements):
        lines = []
        for element in elements:
            if isinstance(element, str):
                lines.append(element)
            elif isinstance(element, (list, tuple)) and element:
                kind = str(element[0]).upper()
                dots = element[1] if len(element) > 1 else ""
                label = element[2] if len(element) > 2 else ""
                if label:
                    lines.append(f"[{kind}] {dots} -> {label}".rstrip())
                elif dots:
                    lines.append(f"[{kind}] {dots}")
                else:
                    lines.append(f"[{kind}]")
        return "\n".join(lines)

    def _mark_dirty(self, message="Unsaved changes"):
        if self._loading:
            return
        self._dirty = True
        self._save_btn.setEnabled(True)
        self._status.setText(message)
        self._refresh_validation_badge()

    def _on_header_changed(self):
        if self._loading:
            return
        self._flush_current_card()
        self._mark_dirty()

    def _on_table_changed(self, item):
        if self._loading or item is None:
            return
        row = item.row()
        if item.column() == 0:
            kind = item.text().strip().upper() or "TEXT"
            if kind not in _OPTION_KINDS and kind != "TEXT":
                self._loading = True
                item.setText("TEXT")
                self._loading = False
        self._flush_current_card()
        if row >= 0:
            self.elem_table.selectRow(row)
        self._mark_dirty()

    def _add_row(self, kind):
        if self._current_card_idx < 0:
            return
        self._loading = True
        self._insert_element_row("" if kind == "TEXT" else [kind])
        self._loading = False
        row = self.elem_table.rowCount() - 1
        self.elem_table.selectRow(row)
        self._flush_current_card()
        self._mark_dirty()

    def _remove_row(self):
        row = self.elem_table.currentRow()
        if row < 0:
            return
        self._loading = True
        self.elem_table.removeRow(row)
        self._loading = False
        self._flush_current_card()
        self._mark_dirty()

    def _move_row(self, delta):
        row = self.elem_table.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self.elem_table.rowCount():
            return
        values = []
        for col in range(self.elem_table.columnCount()):
            item = self.elem_table.item(row, col)
            values.append("" if item is None else item.text())
        target = []
        for col in range(self.elem_table.columnCount()):
            item = self.elem_table.item(new_row, col)
            target.append("" if item is None else item.text())
        self._loading = True
        for col, value in enumerate(target):
            self.elem_table.setItem(row, col, QTableWidgetItem(value))
        for col, value in enumerate(values):
            self.elem_table.setItem(new_row, col, QTableWidgetItem(value))
        self._loading = False
        self.elem_table.selectRow(new_row)
        self._flush_current_card()
        self._mark_dirty()

    def _blank_card(self):
        return {
            "textOffsY": 0,
            "textOffsX": 0,
            "unknown1": 0,
            "textMaxX": 30,
            "unknown2": 0,
            "elements": ["New card"],
            "text": "New card",
        }

    def _add_card(self):
        insert_at = self._current_card_idx + 1 if self._current_card_idx >= 0 else len(self._cards)
        self._flush_current_card()
        self._cards.insert(insert_at, self._blank_card())
        self._current_card_idx = insert_at
        self._rebuild_card_list()
        self.card_list.setCurrentRow(insert_at)
        self._mark_dirty("Added card")

    def _remove_card(self):
        row = self._current_card_idx
        if row < 0 or row >= len(self._cards):
            return
        del self._cards[row]
        if not self._cards:
            self._current_card_idx = -1
            self._rebuild_card_list()
            self._clear_editor()
        else:
            self._current_card_idx = max(0, min(row, len(self._cards) - 1))
            self._rebuild_card_list()
            self.card_list.setCurrentRow(self._current_card_idx)
        self._mark_dirty("Removed card")

    def _move_card(self, delta):
        row = self._current_card_idx
        if row < 0 or row >= len(self._cards):
            return
        new_row = row + delta
        if new_row < 0 or new_row >= len(self._cards):
            return
        self._flush_current_card()
        self._cards[row], self._cards[new_row] = self._cards[new_row], self._cards[row]
        self._current_card_idx = new_row
        self._rebuild_card_list()
        self.card_list.setCurrentRow(new_row)
        self._mark_dirty("Reordered cards")

    def _copy_preview(self):
        QApplication.clipboard().setText(self.preview.toPlainText())

    def _save_txt(self):
        if not self._cards:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Text", "", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return
        parts = []
        for idx, card in enumerate(self._cards):
            parts.append(
                f"--- Card {idx} "
                f"(y={card.get('textOffsY', 0)} x={card.get('textOffsX', 0)} "
                f"maxX={card.get('textMaxX', 0)}) ---"
            )
            parts.append(self._preview_text(card.get("elements", [])))
            parts.append("")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(parts))

    def _save_file(self):
        if (not self._current_file and not self._current_catalog) or not self._cards:
            return
        self._flush_current_card()
        msg_name = self._current_entry_name or os.path.basename(self._current_file)
        msgfiles_names = []
        if self.dl_path:
            msgfiles_path = os.path.join(self.dl_path, "MSGFILES")
            if os.path.isfile(msgfiles_path):
                try:
                    from darklands.extract_cat import listContents
                    msgfiles_names = [name for name, _size, _offs in listContents(msgfiles_path)]
                except Exception:
                    msgfiles_names = []
        report = validate_msg_cards(self._cards, msg_name, msgfiles_names)
        if report.issues:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Validation Warning")
            box.setText("Validation found related MSG issues.")
            box.setInformativeText("Save anyway?")
            box.setDetailedText(summarize_issues(report.issues, max_lines=12))
            save_btn = box.addButton("Save Anyway", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is not save_btn:
                return
        try:
            from darklands.reader_msg import writeBytes, writeData

            if self._current_catalog:
                from darklands.extract_cat import readEntries, writeCat
                entries = readEntries(self._current_catalog)
                raw = writeBytes(self._cards)
                for entry in entries:
                    if entry['name'].upper() == self._current_entry_name.upper():
                        entry['data'] = raw
                        break
                backup = backup_existing_file(self._current_catalog)
                writeCat(self._current_catalog, entries)
                if self._msgfiles_archive is not None and os.path.basename(self._current_catalog).upper() == "MSGFILES":
                    try:
                        from darklands.reader_msgfiles import readData as read_msgfiles
                        self._msgfiles_archive = read_msgfiles(self._current_catalog)
                        self._current_msgfiles_entry = self._msgfiles_archive.get(self._current_entry_name)
                        self._set_file_info(self._describe_msgfiles_entry(self._current_msgfiles_entry))
                    except Exception:
                        pass
                saved_name = (
                    f"{self._current_entry_name} [{os.path.basename(self._current_catalog)}] "
                    f"({backup_label(backup)})"
                )
            else:
                backup = backup_existing_file(self._current_file)
                writeData(self._current_file, self._cards)
                saved_name = f"{os.path.basename(self._current_file)} ({backup_label(backup)})"
            self._dirty = False
            self._original_cards = copy.deepcopy(self._cards)
            self._save_btn.setEnabled(False)
            self._status.setText(f"Saved {saved_name}")
            self._refresh_validation_badge()
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))
