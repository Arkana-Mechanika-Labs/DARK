from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QScrollArea, QFileDialog, QSizePolicy,
    QApplication,
)
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtCore import Qt, QTimer
import traceback


class ConverterWidget(QWidget):
    """Base class for all converter panels.

    Subclasses that need a DL path to run keep _auto_on_path = True (default).
    File-picker converters (PIC, MSG, DRLE, CAT) set _auto_on_path = False and
    manage their own trigger logic.
    """
    _auto_on_path: bool = True   # override to False in file-picker subclasses

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._needs_refresh = True  # triggers first run when shown

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # Title
        title_lbl = QLabel(title)
        f = title_lbl.font()
        f.setPointSize(11)
        f.setBold(True)
        title_lbl.setFont(f)
        root.addWidget(title_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # Optional extra input controls (subclass fills via self.input_layout)
        self.input_widget = QWidget()
        self.input_layout = QVBoxLayout(self.input_widget)
        self.input_layout.setContentsMargins(0, 0, 0, 0)
        self.input_layout.setSpacing(5)
        root.addWidget(self.input_widget)

        # Output widget
        self._output_widget = self._build_output_widget()
        root.addWidget(self._output_widget, stretch=1)

        # Action bar (subclass adds buttons)
        self.action_layout = QHBoxLayout()
        self.action_layout.addStretch()
        root.addLayout(self.action_layout)

    # ── path management ───────────────────────────────────────────────────

    def set_dl_path(self, path: str):
        if path == self.dl_path:
            return
        self.dl_path = path
        if self._auto_on_path and path:
            self._needs_refresh = True
            if self.isVisible():
                QTimer.singleShot(80, self._run_safe)

    # ── Qt events ─────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_on_path and self._needs_refresh and self.dl_path:
            QTimer.singleShot(50, self._run_safe)

    # ── subclass interface ────────────────────────────────────────────────

    def _build_output_widget(self) -> QWidget:
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        f = QFont("Courier New", 9)
        txt.setFont(f)
        self._output_text = txt
        return txt

    def run(self):
        raise NotImplementedError

    # ── helpers ───────────────────────────────────────────────────────────

    def _run_safe(self):
        if not self._needs_refresh:
            return
        self._needs_refresh = False
        try:
            self.run()
        except Exception:
            self._needs_refresh = True
            self._show_error(traceback.format_exc())

    def _force_rerun(self):
        """Bypass the needs-refresh guard (e.g. after a combo-box change)."""
        self._needs_refresh = True
        self._run_safe()

    def _show_text(self, text: str):
        if hasattr(self, '_output_text'):
            self._output_text.setPlainText(text)

    def _show_error(self, msg: str):
        if hasattr(self, '_output_text'):
            self._output_text.setPlainText(f"Error:\n{msg}")
        elif hasattr(self, '_image_label'):
            self._image_label.setText(f"Error:\n{msg}")

    def _need_dl_path(self) -> bool:
        if not self.dl_path:
            self._show_error(
                "DL data path is not set.\n"
                "Use the path bar at the top to point to your Darklands DL/ folder."
            )
            return True
        return False


class TextConverter(ConverterWidget):
    """Converter whose output is plain text."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedWidth(70)
        copy_btn.clicked.connect(self._copy)
        save_btn = QPushButton("Save as TXT…")
        save_btn.clicked.connect(self._save_txt)
        self.action_layout.addWidget(copy_btn)
        self.action_layout.addWidget(save_btn)

    def _copy(self):
        QApplication.clipboard().setText(self._output_text.toPlainText())

    def _save_txt(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Text", "", "Text Files (*.txt);;All Files (*)"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._output_text.toPlainText())


class ImageConverter(ConverterWidget):
    """Converter whose output is an image."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._current_pixmap: QPixmap | None = None
        save_btn = QPushButton("Save as PNG…")
        save_btn.clicked.connect(self._save_png)
        self.action_layout.addWidget(save_btn)

    def _build_output_widget(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._image_label = QLabel("No image loaded")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        scroll.setWidget(self._image_label)
        return scroll

    def _show_pixmap(self, pixmap: QPixmap):
        self._current_pixmap = pixmap
        self._image_label.setPixmap(pixmap)
        self._image_label.resize(pixmap.size())

    def _save_png(self):
        if self._current_pixmap is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PNG", "", "PNG Images (*.png);;All Files (*)"
        )
        if path:
            self._current_pixmap.save(path)
