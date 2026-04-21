import fnmatch
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter,
)
from PySide6.QtCore import Qt

from app.converters.kb_note_dialog import KbNoteDialog
from app.format_coverage import resolve_kb_doc
from app.widgets.hex_view import HexView


class _ResearchFileViewer(QWidget):
    _auto_on_path = True

    def __init__(self, title: str, patterns: tuple[str, ...], kb_doc_rel: str, intro: str, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._patterns = tuple(p.upper() for p in patterns)
        self._kb_doc = resolve_kb_doc(kb_doc_rel)
        self._intro = intro
        self._title_text = title
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        title = QLabel(self._title_text)
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self._summary = QLabel(self._intro)
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        row = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter files...")
        self._filter.textChanged.connect(self._apply_filter)
        row.addWidget(self._filter, stretch=1)
        self._kb_btn = QPushButton("Show KB Note")
        self._kb_btn.clicked.connect(self._show_kb_note)
        self._kb_btn.setEnabled(bool(self._kb_doc))
        row.addWidget(self._kb_btn)
        root.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_detail)
        splitter.addWidget(self._list)

        self._detail = HexView()
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 620])

    def set_dl_path(self, path: str):
        if path == self.dl_path:
            return
        self.dl_path = path
        self._reload()

    def focus_filter(self):
        self._filter.setFocus()
        self._filter.selectAll()

    def _reload(self):
        self._list.clear()
        if not self.dl_path or not os.path.isdir(self.dl_path):
            self._detail.set_message("Set a valid Darklands folder first.")
            return
        matches = []
        for name in sorted(os.listdir(self.dl_path)):
            full = os.path.join(self.dl_path, name)
            if not os.path.isfile(full):
                continue
            upper = name.upper()
            if any(fnmatch.fnmatch(upper, pattern) for pattern in self._patterns):
                matches.append(name)
        for name in matches:
            self._list.addItem(QListWidgetItem(name))
        self._apply_filter()
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._detail.set_message("No matching files found in the current Darklands folder.")

    def _apply_filter(self):
        needle = self._filter.text().strip().lower()
        first = -1
        for row in range(self._list.count()):
            item = self._list.item(row)
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)
            if visible and first < 0:
                first = row
        current = self._list.currentRow()
        if current >= 0 and self._list.item(current).isHidden() and first >= 0:
            self._list.setCurrentRow(first)

    def _show_detail(self, row: int):
        if row < 0 or row >= self._list.count():
            self._detail.set_message("")
            return
        name = self._list.item(row).text()
        path = os.path.join(self.dl_path, name)
        try:
            data = open(path, "rb").read()
        except OSError as exc:
            self._detail.set_message(f"Failed to read {path}\n\n{exc}")
            return
        header = "\n".join(
            [
                f"Name:   {name}",
                f"Path:   {path}",
                f"Bytes:  {len(data):,}",
                f"KB:     {self._kb_doc or '(none)'}",
            ]
        )
        self._detail.set_bytes(data, header=header, max_rows=128)

    def _show_kb_note(self):
        if not self._kb_doc:
            return
        dialog = KbNoteDialog(self._kb_doc, self)
        dialog.exec()


class ImgResearchConverter(_ResearchFileViewer):
    def __init__(self, parent=None):
        super().__init__(
            "IMG Banks (Research)",
            ("*.IMG",),
            "WIP/COMMONSP/COMMONSP_IMG.md",
            "Placeholder viewer for IMG-family research files such as COMMONSP.IMG and BATTLEGR.IMG.",
            parent,
        )


class PanResearchConverter(_ResearchFileViewer):
    def __init__(self, parent=None):
        super().__init__(
            "PAN Sequences (Research)",
            ("*.PAN",),
            "WIP/PAN/PAN_Format.md",
            "Placeholder viewer for PAN presentation sequences while PAN support is still under active research.",
            parent,
        )


class ResearchFilesConverter(_ResearchFileViewer):
    def __init__(self, parent=None):
        super().__init__(
            "Research Files",
            ("LEVEL0.ENM",),
            "20_File_Formats/By_Type/World_Data/darkland.enm.md",
            "Small or unusual files that are related to known formats but do not yet fit the main editor workflows cleanly.",
            parent,
        )
