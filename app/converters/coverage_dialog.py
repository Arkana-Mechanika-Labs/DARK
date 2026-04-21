from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from app.format_coverage import scan_directory


_STATUS_COLORS = {
    "editable": QColor("#63c174"),
    "supported": QColor("#6daae0"),
    "wip": QColor("#d6a553"),
    "runtime": QColor("#9da8b5"),
    "unknown": QColor("#d27c7c"),
}

_STATUS_ORDER = {
    "editable": 0,
    "supported": 1,
    "wip": 2,
    "runtime": 3,
    "unknown": 4,
}


class CoverageDialog(QDialog):
    def __init__(self, dl_path: str, parent=None):
        super().__init__(parent)
        self.dl_path = dl_path
        self.setWindowTitle("Format Coverage")
        self.resize(900, 560)
        self._entries = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter files, families, categories, notes...")
        self._filter.textChanged.connect(self._rebuild_list)
        root.addWidget(self._filter)

        row = QHBoxLayout()
        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Name", "Status", "Category", "Editor"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.currentItemChanged.connect(self._show_detail)
        self._tree.itemDoubleClicked.connect(lambda *_args: self._open_current())
        self._tree.setMinimumWidth(470)
        row.addWidget(self._tree, stretch=0)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        row.addWidget(self._detail, stretch=1)
        root.addLayout(row, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.reload)
        buttons.addButton(refresh_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self._open_btn = QPushButton("Open Editor")
        self._open_btn.clicked.connect(self._open_current)
        buttons.addButton(self._open_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self._kb_btn = QPushButton("Show KB Note")
        self._kb_btn.clicked.connect(self._open_kb_note)
        buttons.addButton(self._kb_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.reload()

    def reload(self):
        report = scan_directory(self.dl_path)
        self._entries = report.entries
        counts = report.counts
        self._summary.setText(
            "Coverage scan for "
            f"{report.root_path or '<no path>'}: "
            f"{counts.get('editable', 0)} editable, "
            f"{counts.get('supported', 0)} supported, "
            f"{counts.get('wip', 0)} WIP, "
            f"{counts.get('runtime', 0)} runtime, "
            f"{counts.get('unknown', 0)} unknown."
        )
        self._rebuild_list()

    def _rebuild_list(self):
        query = self._filter.text().strip().lower()
        self._tree.clear()
        visible = []
        sorted_entries = sorted(
            self._entries,
            key=lambda entry: (
                _STATUS_ORDER.get(entry.status, 99),
                entry.category,
                entry.name.upper(),
            ),
        )
        for entry in sorted_entries:
            haystack = " ".join(
                [
                    entry.name,
                    entry.status_label,
                    entry.category,
                    entry.family,
                    entry.editor_title or "",
                    entry.notes,
                ]
            ).lower()
            if query and query not in haystack:
                continue
            item = QTreeWidgetItem(
                [
                    entry.name,
                    entry.status_label,
                    entry.category.capitalize(),
                    entry.editor_title or "",
                ]
            )
            color = _STATUS_COLORS.get(entry.status)
            if color is not None:
                item.setForeground(1, color)
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            self._tree.addTopLevelItem(item)
            visible.append(item)
        if visible:
            self._tree.setCurrentItem(visible[0])
        else:
            self._detail.setPlainText("No files matched the current filter.")
        self._tree.resizeColumnToContents(0)
        self._tree.resizeColumnToContents(1)
        self._tree.resizeColumnToContents(2)

    def _current_entry(self):
        item = self._tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _show_detail(self, item, _prev=None):
        entry = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if entry is None:
            self._detail.setPlainText("")
            self._open_btn.setEnabled(False)
            self._kb_btn.setEnabled(False)
            return
        lines = [
            f"Name:     {entry.name}",
            f"Path:     {entry.path}",
            f"Status:   {entry.status_label}",
            f"Category: {entry.category}",
            f"Family:   {entry.family}",
            f"Editor:   {entry.editor_title or '(none)'}",
            f"KB Note:  {entry.kb_doc or '(none)'}",
            "",
            entry.notes or "No additional notes.",
        ]
        self._detail.setPlainText("\n".join(lines))
        self._open_btn.setEnabled(bool(entry.editor_title))
        self._kb_btn.setEnabled(bool(entry.kb_doc))

    def _open_current(self):
        entry = self._current_entry()
        if entry is None or not entry.editor_title:
            return
        parent = self.parent()
        handler = getattr(parent, "open_editor", None)
        if callable(handler):
            if handler(entry.editor_title) is not None:
                self.accept()

    def _open_kb_note(self):
        entry = self._current_entry()
        if entry is None or not entry.kb_doc:
            return
        from app.converters.kb_note_dialog import KbNoteDialog

        dialog = KbNoteDialog(entry.kb_doc, self)
        dialog.exec()
