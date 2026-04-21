from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout


class KbNoteDialog(QDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(f"KB Note - {Path(path).name}")
        self.resize(820, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        hdr = QLabel(path)
        hdr.setWordWrap(True)
        root.addWidget(hdr)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        root.addWidget(self._text, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._load_text()

    def _load_text(self):
        try:
            text = Path(self.path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = Path(self.path).read_text(encoding="latin-1")
        except OSError as exc:
            text = f"Failed to load KB note:\n\n{exc}"
        self._text.setPlainText(text)
