"""
Font viewer/editor: renders FONTS.FNT and FONTS.UTL and allows glyph editing.
"""
import os
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_SCALE = 4
_BG = (30, 30, 35)
_FG = (220, 220, 220)
_GRID = (60, 60, 65)


def _render_font_pixmap(font) -> QPixmap:
    chars = font.chars
    if not chars:
        return QPixmap()
    n = len(chars)
    cols = 16
    rows = (n + cols - 1) // cols
    max_w = max(ch.width for ch in chars) if chars else 8
    h = font.height
    cell_w = (max_w + 2) * _SCALE
    cell_h = (h + 2) * _SCALE
    iw = cols * cell_w
    ih = rows * cell_h

    buf = bytearray(iw * ih * 4)
    br, bg, bb = _BG
    for off in range(0, iw * ih * 4, 4):
        buf[off] = bb
        buf[off + 1] = bg
        buf[off + 2] = br
        buf[off + 3] = 255

    gr, gg, gb = _GRID
    for col_idx in range(cols):
        x0 = col_idx * cell_w
        for py in range(ih):
            off = (py * iw + x0) * 4
            buf[off] = gb
            buf[off + 1] = gg
            buf[off + 2] = gr
            buf[off + 3] = 255
    for row_idx in range(rows):
        y0 = row_idx * cell_h
        for px in range(iw):
            off = (y0 * iw + px) * 4
            buf[off] = gb
            buf[off + 1] = gg
            buf[off + 2] = gr
            buf[off + 3] = 255

    fr, fg, fb = _FG
    for idx, ch in enumerate(chars):
        col_idx = idx % cols
        row_idx = idx // cols
        ox = col_idx * cell_w + _SCALE
        oy = row_idx * cell_h + _SCALE
        for y, line in enumerate(ch.lines):
            for x, bit in enumerate(line):
                if not bit:
                    continue
                for dy in range(_SCALE):
                    rs = ((oy + y * _SCALE + dy) * iw) * 4
                    for dx in range(_SCALE):
                        off = rs + (ox + x * _SCALE + dx) * 4
                        buf[off] = fb
                        buf[off + 1] = fg
                        buf[off + 2] = fr
                        buf[off + 3] = 255

    img = QImage(bytes(buf), iw, ih, QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(img)


def _render_char_pixmap(font, char) -> QPixmap:
    width = max(1, max(char.width, 1))
    height = max(1, font.height)
    pad = 1
    iw = (width + pad * 2) * 12
    ih = (height + pad * 2) * 12
    buf = bytearray(iw * ih * 4)
    br, bg, bb = _BG
    for off in range(0, iw * ih * 4, 4):
        buf[off] = bb
        buf[off + 1] = bg
        buf[off + 2] = br
        buf[off + 3] = 255

    gr, gg, gb = _GRID
    cell = 12
    for x in range(width + 1):
        px = (pad + x) * cell
        for py in range(ih):
            off = (py * iw + min(px, iw - 1)) * 4
            buf[off] = gb
            buf[off + 1] = gg
            buf[off + 2] = gr
            buf[off + 3] = 255
    for y in range(height + 1):
        py = (pad + y) * cell
        for px in range(iw):
            off = (min(py, ih - 1) * iw + px) * 4
            buf[off] = gb
            buf[off + 1] = gg
            buf[off + 2] = gr
            buf[off + 3] = 255

    fr, fg, fb = _FG
    for y, line in enumerate(char.lines):
        for x, bit in enumerate(line):
            if not bit:
                continue
            for dy in range(cell):
                rs = (((pad + y) * cell + dy) * iw) * 4
                for dx in range(cell):
                    off = rs + (((pad + x) * cell + dx) * 4)
                    buf[off] = fb
                    buf[off + 1] = fg
                    buf[off + 2] = fr
                    buf[off + 3] = 255

    img = QImage(bytes(buf), iw, ih, QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(img)


class _FontTab(QWidget):
    def __init__(self, ext, save_callback, parent=None):
        super().__init__(parent)
        self.ext = ext
        self._save_callback = save_callback
        self._fonts = []
        self._loading = False
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Font:"))
        self.font_combo = QComboBox()
        self.font_combo.currentIndexChanged.connect(self._on_font_changed)
        top.addWidget(self.font_combo)
        top.addWidget(QLabel("Glyph:"))
        self.char_combo = QComboBox()
        self.char_combo.currentIndexChanged.connect(self._on_char_changed)
        top.addWidget(self.char_combo)
        top.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 32)
        self.width_spin.valueChanged.connect(self._mark_dirty)
        top.addWidget(self.width_spin)
        top.addStretch()
        layout.addLayout(top)

        self.info_lbl = QLabel("")
        layout.addWidget(self.info_lbl)

        mid = QHBoxLayout()

        left = QVBoxLayout()
        left.addWidget(QLabel("Glyph bitmap (# = set, . = clear)"))
        self.bitmap_edit = QPlainTextEdit()
        self.bitmap_edit.setFont(QFont("Courier New", 10))
        self.bitmap_edit.textChanged.connect(self._mark_dirty)
        left.addWidget(self.bitmap_edit, stretch=1)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply Glyph")
        apply_btn.clicked.connect(self._apply_glyph)
        btn_row.addWidget(apply_btn)
        revert_btn = QPushButton("Revert Glyph")
        revert_btn.clicked.connect(self._reload_current_glyph)
        btn_row.addWidget(revert_btn)
        btn_row.addStretch()
        self.save_btn = QPushButton(f"Save {ext}")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_fonts)
        btn_row.addWidget(self.save_btn)
        left.addLayout(btn_row)

        mid.addLayout(left, stretch=1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Glyph preview"))
        self.char_preview = QLabel()
        self.char_preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.char_preview.setMinimumWidth(220)
        right.addWidget(self.char_preview)

        right.addWidget(QLabel("Whole font preview"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.font_preview = QLabel()
        self.font_preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.font_preview)
        right.addWidget(scroll, stretch=1)

        mid.addLayout(right, stretch=1)
        layout.addLayout(mid, stretch=1)

    def load_fonts(self, fonts):
        self._fonts = fonts
        self._dirty = False
        self.save_btn.setEnabled(False)

        self._loading = True
        self.font_combo.clear()
        for i, fnt in enumerate(fonts):
            self.font_combo.addItem(
                f"Font {i} (chars {fnt.start_char}-{fnt.end_char}, h={fnt.height})"
            )
        self.char_combo.clear()
        self.bitmap_edit.clear()
        self.font_preview.clear()
        self.char_preview.clear()
        self._loading = False

        if fonts:
            self.font_combo.setCurrentIndex(0)
            self._on_font_changed(0)

    def _current_font(self):
        idx = self.font_combo.currentIndex()
        if idx < 0 or idx >= len(self._fonts):
            return None
        return self._fonts[idx]

    def _current_char(self):
        font = self._current_font()
        idx = self.char_combo.currentIndex()
        if font is None or idx < 0 or idx >= len(font.chars):
            return None
        return font.chars[idx]

    def _on_font_changed(self, idx):
        font = self._current_font()
        self._loading = True
        self.char_combo.clear()
        if font is not None:
            for i, _ in enumerate(font.chars):
                code = font.start_char + i
                label = chr(code) if 32 <= code < 127 else "."
                self.char_combo.addItem(f"{code:3d}  '{label}'")
            self.info_lbl.setText(
                f"Height: {font.height}  Chars: {len(font.chars)}  "
                f"ASCII range: {font.start_char}-{font.end_char}  bw: {font.bw}"
            )
            pix = _render_font_pixmap(font)
            self.font_preview.setPixmap(pix)
            self.font_preview.resize(pix.size())
        else:
            self.info_lbl.setText("")
            self.font_preview.clear()
        self._loading = False
        if font is not None and font.chars:
            self.char_combo.setCurrentIndex(0)
            self._on_char_changed(0)

    def _on_char_changed(self, idx):
        if self._loading:
            return
        self._reload_current_glyph()

    def _reload_current_glyph(self):
        font = self._current_font()
        char = self._current_char()
        if font is None or char is None:
            return
        self._loading = True
        self.width_spin.setValue(max(1, char.width))
        rows = []
        for line in char.lines:
            rows.append("".join("#" if bit else "." for bit in line))
        self.bitmap_edit.setPlainText("\n".join(rows))
        self._loading = False
        self._refresh_char_preview()

    def _refresh_char_preview(self):
        font = self._current_font()
        char = self._current_char()
        if font is None or char is None:
            self.char_preview.clear()
            return
        pix = _render_char_pixmap(font, char)
        self.char_preview.setPixmap(pix)

    def _mark_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self.save_btn.setEnabled(True)

    def _apply_glyph(self):
        font = self._current_font()
        char = self._current_char()
        if font is None or char is None:
            return

        width = self.width_spin.value()
        lines = self.bitmap_edit.toPlainText().splitlines()
        if len(lines) != font.height:
            QMessageBox.warning(
                self,
                "Invalid glyph",
                f"Expected exactly {font.height} rows for this font.",
            )
            return

        new_lines = []
        for raw_line in lines:
            normalized = raw_line.rstrip()
            row = []
            for x in range(width):
                ch = normalized[x] if x < len(normalized) else "."
                row.append(1 if ch in "#1Xx@" else 0)
            new_lines.append(row)

        char.width = width
        char.lines = new_lines
        self._dirty = True
        self.save_btn.setEnabled(True)
        self._refresh_char_preview()
        pix = _render_font_pixmap(font)
        self.font_preview.setPixmap(pix)
        self.font_preview.resize(pix.size())

    def _save_fonts(self):
        self._apply_glyph()
        self._save_callback(self.ext)
        self._dirty = False
        self.save_btn.setEnabled(False)


class FontConverter(QWidget):
    """Font editor for FONTS.FNT / FONTS.UTL."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._needs_refresh = True
        self._fonts = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        title = QLabel("Font Editor (FONTS.FNT / FONTS.UTL)")
        f = title.font()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        self.tabs = QTabWidget()
        self._fnt_tab = _FontTab("FNT", self._save_fonts)
        self._utl_tab = _FontTab("UTL", self._save_fonts)
        self.tabs.addTab(self._fnt_tab, "FONTS.FNT")
        self.tabs.addTab(self._utl_tab, "FONTS.UTL")
        layout.addWidget(self.tabs, stretch=1)

    def set_dl_path(self, path: str):
        if path == self.dl_path:
            return
        self.dl_path = path
        if path:
            self._needs_refresh = True
            if self.isVisible():
                QTimer.singleShot(80, self._run_safe)

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh and self.dl_path:
            QTimer.singleShot(50, self._run_safe)

    def _run_safe(self):
        if not self._needs_refresh:
            return
        self._needs_refresh = False
        try:
            self._load()
        except Exception:
            QMessageBox.critical(self, "Error", traceback.format_exc())
            self._needs_refresh = True

    def _load(self):
        from darklands.format_fnt import readData

        self._fonts = readData(self.dl_path)
        self._fnt_tab.load_fonts(self._fonts.get("FNT", []))
        self._utl_tab.load_fonts(self._fonts.get("UTL", []))

    def _save_fonts(self, ext):
        if not self.dl_path:
            QMessageBox.warning(self, "No path", "DL data path is not set.")
            return
        from darklands.format_fnt import write_fonts

        path = os.path.join(self.dl_path, f"FONTS.{ext}")
        write_fonts(path, self._fonts.get(ext, []))
