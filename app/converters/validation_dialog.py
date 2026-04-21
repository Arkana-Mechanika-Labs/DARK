from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.validation import summarize_issues, validate_world_data


class ValidationDialog(QDialog):
    def __init__(self, dl_path: str, parent=None):
        super().__init__(parent)
        self.dl_path = dl_path
        self.setWindowTitle("Validation Report")
        self.resize(760, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        row = QHBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_detail)
        self._list.itemDoubleClicked.connect(lambda *_args: self._open_current())
        row.addWidget(self._list, stretch=0)
        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        row.addWidget(self._detail, stretch=1)
        root.addLayout(row, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.reload)
        buttons.addButton(refresh_btn, QDialogButtonBox.ButtonRole.ActionRole)
        open_btn = QPushButton("Open Issue")
        open_btn.clicked.connect(self._open_current)
        buttons.addButton(open_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._issues = []
        self.reload()

    def reload(self):
        report = validate_world_data(self.dl_path)
        self._issues = report.issues
        errors = len(report.errors)
        warnings = len(report.warnings)
        self._summary.setText(
            f"{errors} error(s), {warnings} warning(s) found in {self.dl_path or '<no path>'}."
        )
        self._list.clear()
        for issue in self._issues:
            self._list.addItem(f"{issue.severity.upper():7s}  [{issue.scope}] {issue.message}")
        if self._issues:
            self._list.setCurrentRow(0)
        else:
            self._detail.setPlainText("No validation issues found.")

    def _show_detail(self, row: int):
        if row < 0 or row >= len(self._issues):
            self._detail.setPlainText("")
            return
        issue = self._issues[row]
        self._detail.setPlainText(
            summarize_issues([issue], max_lines=1)
        )

    def _open_current(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._issues):
            return
        parent = self.parent()
        handler = getattr(parent, "navigate_to_validation_issue", None)
        if callable(handler):
            if handler(self._issues[row]):
                self.accept()
