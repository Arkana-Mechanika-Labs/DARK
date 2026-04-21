"""
Image converters: PIC viewer (file-list browser) and DRLE decompressor.
"""
import io
import os
import re
import traceback
from functools import lru_cache
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QSplitter, QListWidget, QListWidgetItem, QScrollArea,
    QFrame, QSizePolicy, QApplication, QMessageBox, QComboBox,
    QSpinBox, QCheckBox,
)
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QIcon
from PySide6.QtCore import Qt, QEvent, QTimer, QSize

from .base import ConverterWidget, TextConverter
from app.widgets.hex_view import HexView


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _bytes_to_pixmap(rgba_bytes: bytes, width: int, height: int) -> QPixmap:
    img = QImage(rgba_bytes, width, height, QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(img)


def _render_palette_pixmap(pal, cell: int = 20) -> QPixmap:
    """Render a 256-entry palette as a 16x16 grid of colored squares."""
    iw, ih = 16 * cell, 16 * cell
    buf = bytearray(iw * ih * 4)
    for i, c in enumerate(pal):
        if c is None:
            continue
        ci, ri = i % 16, i // 16
        r_val, g_val, b_val = c
        for dy in range(cell):
            row_start = (ri * cell + dy) * iw * 4
            for dx in range(cell):
                off = row_start + (ci * cell + dx) * 4
                buf[off]     = b_val
                buf[off + 1] = g_val
                buf[off + 2] = r_val
                buf[off + 3] = 255
    img = QImage(bytes(buf), iw, ih, QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(img)


@lru_cache(maxsize=8)
def _load_enemy_preview_context(dl_path: str):
    from darklands.reader_enemypal import readData as read_enemy_palettes
    from darklands.reader_enm import readData as read_enemies
    from darklands.palette_context import load_combat_palette

    enemy_types, enemies = read_enemies(dl_path)
    palette_chunks = read_enemy_palettes(dl_path)
    return enemy_types, enemies, palette_chunks, load_combat_palette(dl_path)


def _default_enemy_palette_selection(enemy_type: dict | None):
    selection = {32: None, 48: None, 64: None}
    if not enemy_type:
        return selection
    pal_start = int(enemy_type.get("pal_start", 0))
    pal_cnt = max(1, int(enemy_type.get("pal_cnt", 0)))
    block_choice = pal_start
    name = str(enemy_type.get("name", ""))
    digits = "".join(ch for ch in name if ch.isdigit())
    if digits:
        variant_idx = max(0, min(int(digits) - 1, pal_cnt - 1))
        block_choice = pal_start + variant_idx
    selection[int(enemy_type.get("palette_block_hint", 64))] = block_choice
    return selection


def _build_enemy_palette(base_palette, palette_chunks, block_selection: dict[int, int]):
    palette = list(base_palette)
    applied = []
    chunk_by_index = {chunk.get("index", -1): chunk for chunk in palette_chunks}
    for block, chunk_index in sorted(block_selection.items()):
        if chunk_index is None:
            continue
        chunk = chunk_by_index.get(chunk_index)
        if not chunk:
            continue
        start = chunk.get("start_index", 0)
        if start != block:
            continue
        for offset, color in enumerate(chunk.get("colors", [])):
            slot = start + offset
            if 0 <= slot < len(palette):
                palette[slot] = color
        applied.append(f"{block}-{block + 15}: #{chunk_index}")
    return palette, ", ".join(applied) if applied else "combat base palette"


def _enemy_palette_for_group(dl_path: str, image_group: str):
    from darklands.palette_context import load_combat_palette

    try:
        enemy_types, _, palette_chunks, base_palette = _load_enemy_preview_context(dl_path)
    except Exception:
        base_palette = load_combat_palette(dl_path)
        return list(base_palette), None, "combat base palette", {}

    enemy_type = next(
        (et for et in enemy_types if et.get("image_group", "").upper() == image_group.upper()),
        None,
    )
    if enemy_type is None:
        return list(base_palette), None, "combat base palette", {}

    pal_start = int(enemy_type.get("pal_start", 0))
    pal_cnt = max(1, int(enemy_type.get("pal_cnt", 0)))
    relevant_chunks = [
        chunk for chunk in palette_chunks
        if pal_start <= chunk.get("index", -1) < pal_start + pal_cnt
    ]
    if relevant_chunks:
        enemy_type["palette_block_hint"] = relevant_chunks[0].get("block_index", 64)
    selection = _default_enemy_palette_selection(enemy_type)
    palette, summary = _build_enemy_palette(base_palette, palette_chunks, selection)
    return palette, enemy_type, summary, selection


# ---------------------------------------------------------------------------
# PIC viewer — standalone widget with side-by-side file list + image
# ---------------------------------------------------------------------------

class PicConverter(QWidget):
    """Browse .PIC files; clicking one loads it immediately — no Run button."""

    # Canonical zoom steps (fraction of original size)
    _ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._current_pic = None
        self._current_pixmap: QPixmap | None = None
        self._selected_file: str | None = None
        self._zoom: float = 3.0
        self._last_palette = None
        self._last_palette_source = ""
        self._palette_data_cache = {}
        self._folder_pic_index = {}
        self._resolved_palette_cache = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # Title
        title = QLabel("PIC Image Viewer")
        f = title.font(); f.setPointSize(11); f.setBold(True); title.setFont(f)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # Splitter: file list | image
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        # ── Left: folder + file list ─────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(150)
        left.setMaximumWidth(260)
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 6, 0)
        llay.setSpacing(4)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(4)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder…")
        self.folder_edit.setReadOnly(True)
        folder_row.addWidget(self.folder_edit)
        browse_folder_btn = QPushButton("…")
        browse_folder_btn.setFixedWidth(28)
        browse_folder_btn.setToolTip("Browse for a folder containing .PIC files")
        browse_folder_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_folder_btn)
        llay.addLayout(folder_row)

        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self._on_file_clicked)
        llay.addWidget(self.file_list)

        splitter.addWidget(left)

        # ── Right: options + image scroll area ───────────────────────────
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(4, 0, 0, 0)
        rlay.setSpacing(4)

        # Palette override row
        pal_row = QHBoxLayout()
        pal_row.setSpacing(4)
        pal_row.addWidget(QLabel("Palette override:"))
        self.pal_edit = QLineEdit()
        self.pal_edit.setPlaceholderText("Leave blank for automatic palette resolution")
        pal_row.addWidget(self.pal_edit)
        pal_btn = QPushButton("…")
        pal_btn.setFixedWidth(28)
        pal_btn.clicked.connect(self._browse_pal)
        pal_row.addWidget(pal_btn)
        rlay.addLayout(pal_row)

        self._palette_info = QLabel("")
        self._palette_info.setWordWrap(True)
        self._palette_info.setStyleSheet("color: #666; font-size: 8pt;")
        rlay.addWidget(self._palette_info)


        # ── Zoom controls ─────────────────────────────────────────────────
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(4)
        zoom_row.addStretch()
        zoom_row.addWidget(QLabel("Zoom:"))

        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedWidth(26)
        zoom_out_btn.setToolTip("Zoom out  (Ctrl + scroll down)")
        zoom_out_btn.clicked.connect(self._zoom_out)
        zoom_row.addWidget(zoom_out_btn)

        self._zoom_label = QLabel("300%")
        self._zoom_label.setFixedWidth(44)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_row.addWidget(self._zoom_label)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(26)
        zoom_in_btn.setToolTip("Zoom in  (Ctrl + scroll up)")
        zoom_in_btn.clicked.connect(self._zoom_in)
        zoom_row.addWidget(zoom_in_btn)

        zoom_1_btn = QPushButton("1:1")
        zoom_1_btn.setFixedWidth(34)
        zoom_1_btn.setToolTip("Reset to actual size")
        zoom_1_btn.clicked.connect(self._zoom_reset)
        zoom_row.addWidget(zoom_1_btn)

        rlay.addLayout(zoom_row)

        # ── Image display ─────────────────────────────────────────────────
        preview_split = QSplitter(Qt.Orientation.Vertical)
        rlay.addWidget(preview_split, stretch=1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)   # we manage label size manually
        self._image_label = QLabel("Select a PIC file from the list")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._image_label)
        self._scroll.viewport().installEventFilter(self)  # Ctrl+wheel → zoom
        preview_split.addWidget(self._scroll)

        palette_panel = QFrame()
        palette_panel.setFrameShape(QFrame.Shape.StyledPanel)
        palette_lay = QVBoxLayout(palette_panel)
        palette_lay.setContentsMargins(6, 6, 6, 6)
        palette_lay.setSpacing(4)
        palette_title = QLabel("Palette")
        palette_title.setStyleSheet("font-weight: bold;")
        palette_lay.addWidget(palette_title)
        self._palette_scroll = QScrollArea()
        self._palette_scroll.setWidgetResizable(False)
        self._palette_label = QLabel("Palette preview will appear here.")
        self._palette_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._palette_scroll.setWidget(self._palette_label)
        palette_lay.addWidget(self._palette_scroll, stretch=1)
        preview_split.addWidget(palette_panel)
        preview_split.setStretchFactor(0, 1)
        preview_split.setStretchFactor(1, 0)
        preview_split.setSizes([560, 210])

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 700])

        # Action buttons
        action_row = QHBoxLayout()
        action_row.addStretch()
        save_pic_btn = QPushButton("Save PIC")
        save_pic_btn.clicked.connect(self._save_pic)
        action_row.addWidget(save_pic_btn)
        save_btn = QPushButton("Save as PNG…")
        save_btn.clicked.connect(self._save_png)
        action_row.addWidget(save_btn)
        root.addLayout(action_row)

    # ── path / folder management ──────────────────────────────────────────

    def set_dl_path(self, path: str):
        self.dl_path = path
        self._clear_palette_caches()
        pics_path = os.path.join(path, "PICS") if path else path
        default = pics_path if os.path.isdir(pics_path) else path
        self.folder_edit.setText(default)
        self._refresh_list(default)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select PIC Folder",
            self.folder_edit.text() or self.dl_path or ""
        )
        if path:
            self.folder_edit.setText(path)
            self._clear_palette_caches()
            self._refresh_list(path)

    def _clear_palette_caches(self):
        self._palette_data_cache.clear()
        self._folder_pic_index.clear()
        self._resolved_palette_cache.clear()

    def _browse_pal(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Palette Source",
            self.dl_path or "",
            "PIC Files (*.PIC *.pic);;All Files (*)"
        )
        if path:
            self.pal_edit.setText(path)
            self._reload()

    def _normalized_pic_name(self, path_or_name: str) -> str:
        stem = os.path.splitext(os.path.basename(path_or_name))[0].upper()
        stem = re.sub(r'[^A-Z0-9]', '', stem)
        changed = True
        while changed:
            changed = False
            for suffix in ("SMALL", "STAT", "SHORT", "ICON", "PALT", "BACK", "SCRN", "LIT"):
                if stem.endswith(suffix) and len(stem) > len(suffix):
                    stem = stem[:-len(suffix)]
                    changed = True
        stem = re.sub(r'\d+$', '', stem)
        return stem

    def _palette_candidates(self, selected_file: str) -> list[str]:
        folder = os.path.dirname(selected_file)
        stem = os.path.splitext(os.path.basename(selected_file))[0].upper()
        base = self._normalized_pic_name(selected_file)
        candidates = []

        def add(name: str):
            path = os.path.join(folder, name)
            if path not in candidates and os.path.isfile(path):
                candidates.append(path)

        if stem.endswith("SMALL"):
            add(stem[:-5] + "SHORT.PIC")
        if stem.endswith("STAT"):
            add(stem[:-4] + "SHORT.PIC")
        if stem.endswith("ICON"):
            add(base + "PALT.PIC")
            add(base + "GEN.PIC")
        if stem.startswith("MAP"):
            add("MAPICONS.PIC")
            add("MAPICON2.PIC")
        if stem.startswith("ALC"):
            add("ALCSCRN0.PIC")
            add("ALCSCRN1.PIC")
            add("BKGDALCM.PIC")
            add("ALCCART9.PIC")
            add("ALCEM2.PIC")
        if stem.startswith("ARMBRS") or stem.startswith("ARMBRSH"):
            add("ARMBACK.PIC")
        if stem.startswith("ARMSBACK"):
            add("ARMBACK.PIC")
        if stem.startswith("BUTTON"):
            add("COMMON.PIC")
        if stem.startswith("CHAR"):
            add("CHARPALT.PIC")

        return candidates

    def _load_palette_only(self, path: str):
        cached = self._palette_data_cache.get(path)
        if cached is not None:
            return list(cached) if cached else None
        from darklands.format_pic import Pic

        try:
            pal_pic = Pic(path)
            pal_pic.read_file(path, palOnly=True)
            palette = list(pal_pic.pal) if pal_pic.pal else None
        except Exception:
            palette = None
        self._palette_data_cache[path] = list(palette) if palette else None
        return list(palette) if palette else None

    def _folder_index(self, folder: str):
        cached = self._folder_pic_index.get(folder)
        if cached is not None:
            return cached
        donors = []
        try:
            for name in os.listdir(folder):
                if not name.upper().endswith('.PIC'):
                    continue
                donors.append({
                    'name': name,
                    'path': os.path.join(folder, name),
                    'norm': self._normalized_pic_name(name),
                })
        except OSError:
            donors = []
        self._folder_pic_index[folder] = donors
        return donors

    def _resolve_palette(self, selected_file: str, pic):
        from darklands.format_pic import default_pal

        override = self.pal_edit.text().strip()
        selected_stem = os.path.splitext(os.path.basename(selected_file))[0].upper()
        cache_key = (selected_file, override)
        cached = self._resolved_palette_cache.get(cache_key)
        if cached is not None:
            palette, source = cached
            return list(palette), source
        if override and os.path.isfile(override):
            palette = self._load_palette_only(override)
            if palette:
                result = (list(palette), f"Manual override: {os.path.basename(override)}")
                self._resolved_palette_cache[cache_key] = (list(result[0]), result[1])
                return list(result[0]), result[1]

        if pic.pal:
            result = (list(pic.pal), "Embedded M0 palette")
            self._resolved_palette_cache[cache_key] = (list(result[0]), result[1])
            return list(result[0]), result[1]

        for candidate in self._palette_candidates(selected_file):
            palette = self._load_palette_only(candidate)
            if palette:
                result = (list(palette), f"Auto palette: {os.path.basename(candidate)}")
                self._resolved_palette_cache[cache_key] = (list(result[0]), result[1])
                return list(result[0]), result[1]

        folder = os.path.dirname(selected_file)
        selected_norm = self._normalized_pic_name(selected_file)
        donors = []
        for donor in self._folder_index(folder):
            donor_norm = donor['norm']
            score = 0
            if donor_norm == selected_norm:
                score += 100
            if selected_stem.startswith(donor_norm[:max(1, min(4, len(donor_norm)))]) or donor_norm.startswith(selected_stem[:max(1, min(4, len(selected_stem)))]):
                score += 35
            common_prefix = len(os.path.commonprefix([donor_norm, selected_norm]))
            score += common_prefix * 5
            if selected_norm and donor_norm.startswith(selected_norm[:max(1, min(4, len(selected_norm)))]):
                score += 15
            donors.append({
                'score': score,
                'donor': donor,
            })
        donors.sort(
            key=lambda entry: (
                entry['score'],
                len(entry['donor']['norm']),
                entry['donor']['name'],
            ),
            reverse=True,
        )
        for ranked in donors:
            if ranked['score'] < 15:
                break
            donor = ranked['donor']
            palette = self._load_palette_only(donor['path'])
            if palette:
                result = (list(palette), f"Auto palette: {os.path.basename(donor['path'])}")
                self._resolved_palette_cache[cache_key] = (list(result[0]), result[1])
                return list(result[0]), result[1]

        for common in ("COMMON.PIC", "CHARGEN.PIC", "CHARPALT.PIC", "LOADSCRN.PIC"):
            common_path = os.path.join(folder, common)
            if os.path.isfile(common_path):
                palette = self._load_palette_only(common_path)
                if palette:
                    result = (list(palette), f"Fallback palette: {common}")
                    self._resolved_palette_cache[cache_key] = (list(result[0]), result[1])
                    return list(result[0]), result[1]

        if self._last_palette:
            result = (list(self._last_palette), f"Previous palette: {self._last_palette_source}")
            self._resolved_palette_cache[cache_key] = (list(result[0]), result[1])
            return list(result[0]), result[1]

        result = (list(default_pal), "Fallback: default VGA palette")
        self._resolved_palette_cache[cache_key] = (list(result[0]), result[1])
        return list(result[0]), result[1]

    def _refresh_list(self, folder: str):
        self.file_list.clear()
        if not folder or not os.path.isdir(folder):
            return
        files = sorted(
            f for f in os.listdir(folder) if f.upper().endswith('.PIC')
        )
        for fname in files:
            self.file_list.addItem(fname)

    # ── file load ─────────────────────────────────────────────────────────

    def _on_file_clicked(self, item: QListWidgetItem):
        folder = self.folder_edit.text() or self.dl_path
        if not folder:
            return
        fpath = os.path.join(folder, item.text())
        self._selected_file = fpath
        self._reload()

    def _reload(self):
        if not self._selected_file:
            return
        try:
            from darklands.format_pic import Pic, default_pal
            pic = Pic(self._selected_file)
            resolved_pal, resolved_src = self._resolve_palette(self._selected_file, pic)
            pic.pal = list(resolved_pal or default_pal)
            self._palette_info.setText(f"Resolved palette: {resolved_src}")

            if pic.pic:
                rgba, w, h = pic.render_rgba_bytes()
                pixmap = _bytes_to_pixmap(rgba, w, h)
            else:
                pixmap = QPixmap()

            self._current_pic = pic
            self._current_pixmap = pixmap
            self._last_palette = list(pic.pal) if pic.pal else None
            self._last_palette_source = resolved_src
            pal_pixmap = _render_palette_pixmap(pic.pal or default_pal, cell=12)
            self._palette_label.setPixmap(pal_pixmap)
            self._palette_label.resize(pal_pixmap.size())
            self._palette_label.setText("")
            self._apply_zoom()
        except Exception:
            self._image_label.setText(f"Error:\n{traceback.format_exc()}")

    # ── zoom ──────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """Intercept Ctrl+scroll on the image viewport to zoom."""
        if (obj is self._scroll.viewport()
                and event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if event.angleDelta().y() > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            return True          # consumed — don't scroll
        return super().eventFilter(obj, event)

    def _zoom_in(self):
        steps = [z for z in self._ZOOM_STEPS if z > self._zoom + 1e-9]
        if steps:
            self._set_zoom(steps[0])

    def _zoom_out(self):
        steps = [z for z in self._ZOOM_STEPS if z < self._zoom - 1e-9]
        if steps:
            self._set_zoom(steps[-1])

    def _zoom_reset(self):
        self._set_zoom(1.0)

    def _set_zoom(self, zoom: float):
        self._zoom = zoom
        pct = int(round(zoom * 100))
        self._zoom_label.setText(f"{pct}%")
        self._apply_zoom()

    def _apply_zoom(self):
        if self._current_pixmap is None:
            return
        pm = self._current_pixmap
        if pm.isNull():
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("No image data in this PIC")
            return
        if abs(self._zoom - 1.0) < 1e-9:
            scaled = pm
        else:
            w = max(1, int(pm.width()  * self._zoom))
            h = max(1, int(pm.height() * self._zoom))
            scaled = pm.scaled(
                w, h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self._image_label.setPixmap(scaled)
        self._image_label.resize(scaled.size())

    # ── actions ───────────────────────────────────────────────────────────

    def _save_png(self):
        if self._current_pixmap is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PNG", "", "PNG Images (*.png);;All Files (*)"
        )
        if path:
            self._current_pixmap.save(path)

    def _save_pic(self):
        if self._current_pic is None or not self._selected_file:
            return
        try:
            self._current_pic.write_file(self._selected_file)
            self._clear_palette_caches()
            QMessageBox.information(
                self,
                "Saved",
                f"Saved {os.path.basename(self._selected_file)}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))


# ---------------------------------------------------------------------------
# IMC viewer — browse tactical sprite catalogs with frame stepping
# ---------------------------------------------------------------------------

class ImcConverter(QWidget):
    _ZOOM_STEPS = [0.5, 0.67, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._cat_entries = {}
        self._frames = []
        self._frame_pixmaps = []
        self._frame_idx = 0
        self._current_pixmap: QPixmap | None = None
        self._zoom = 8.0
        self._selected_cat = ""
        self._selected_entry = ""
        self._cat_dirty = {}
        self._current_palette = []
        self._current_imc = None
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(120)
        self._play_timer.timeout.connect(self._next_frame)
        self._syncing_thumb = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        title = QLabel("IMC Sprite Viewer")
        f = title.font(); f.setPointSize(11); f.setBold(True); title.setFont(f)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Catalog:"))
        self.cat_combo = QComboBox()
        self.cat_combo.currentIndexChanged.connect(self._on_cat_changed)
        top_row.addWidget(self.cat_combo, stretch=1)
        top_row.addWidget(QLabel("Palette:"))
        self.palette_combo = QComboBox()
        self.palette_combo.addItem("Enemy palette (auto)", "auto")
        self.palette_combo.addItem("Default VGA", "default")
        self.palette_combo.currentIndexChanged.connect(self._reload_current_entry)
        top_row.addWidget(self.palette_combo)
        root.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        left = QWidget()
        left.setMinimumWidth(180)
        left.setMaximumWidth(300)
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 6, 0)
        llay.setSpacing(4)
        llay.addWidget(QLabel("Entries:"))
        self.entry_list = QListWidget()
        self.entry_list.itemClicked.connect(self._on_entry_clicked)
        llay.addWidget(self.entry_list)
        splitter.addWidget(left)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(4, 0, 0, 0)
        rlay.setSpacing(4)

        self.info_label = QLabel("Select an IMC entry from a tactical catalog.")
        self.info_label.setWordWrap(True)
        rlay.addWidget(self.info_label)

        nav_row = QHBoxLayout()
        self.prev_btn = QPushButton("Prev")
        self.prev_btn.clicked.connect(self._prev_frame)
        nav_row.addWidget(self.prev_btn)
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._toggle_playback)
        nav_row.addWidget(self.play_btn)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self._next_frame)
        nav_row.addWidget(self.next_btn)
        nav_row.addWidget(QLabel("Frame:"))
        self.frame_spin = QSpinBox()
        self.frame_spin.setMinimum(1)
        self.frame_spin.setMaximum(1)
        self.frame_spin.valueChanged.connect(self._on_frame_spin)
        nav_row.addWidget(self.frame_spin)
        nav_row.addWidget(QLabel("Zoom:"))
        self.zoom_combo = QComboBox()
        for step in self._ZOOM_STEPS:
            self.zoom_combo.addItem(f"{int(step * 100)}%", step)
        self.zoom_combo.setCurrentText("800%")
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        nav_row.addWidget(self.zoom_combo)
        nav_row.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        for label, ms in (
            ("Slow", 220),
            ("Normal", 120),
            ("Fast", 70),
            ("Very Fast", 40),
        ):
            self.speed_combo.addItem(label, ms)
        self.speed_combo.setCurrentText("Normal")
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        nav_row.addWidget(self.speed_combo)
        self.grid_check = QCheckBox("Grid")
        self.grid_check.toggled.connect(self._apply_zoom)
        nav_row.addWidget(self.grid_check)
        nav_row.addStretch()
        rlay.addLayout(nav_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._image_host = QWidget()
        self._image_host_layout = QVBoxLayout(self._image_host)
        self._image_host_layout.setContentsMargins(16, 16, 16, 16)
        self._image_host_layout.addStretch()
        self._image_label = QLabel("No frame")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_host_layout.addWidget(self._image_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self._image_host_layout.addStretch()
        self._scroll.setWidget(self._image_host)
        self._scroll.viewport().installEventFilter(self)
        rlay.addWidget(self._scroll, stretch=1)

        thumb_frame = QFrame()
        thumb_frame.setFrameShape(QFrame.Shape.StyledPanel)
        thumb_lay = QVBoxLayout(thumb_frame)
        thumb_lay.setContentsMargins(6, 6, 6, 6)
        thumb_lay.setSpacing(4)
        thumb_hdr = QLabel("Frames")
        thumb_hdr.setStyleSheet("font-weight: bold;")
        thumb_lay.addWidget(thumb_hdr)
        self.thumb_list = QListWidget()
        self.thumb_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumb_list.setFlow(QListWidget.Flow.LeftToRight)
        self.thumb_list.setWrapping(False)
        self.thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumb_list.setIconSize(QSize(48, 48))
        self.thumb_list.setMaximumHeight(102)
        self.thumb_list.currentRowChanged.connect(self._on_thumb_selected)
        thumb_lay.addWidget(self.thumb_list)
        rlay.addWidget(thumb_frame)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self.export_imc_btn = QPushButton("Export IMC...")
        self.export_imc_btn.clicked.connect(self._export_imc)
        action_row.addWidget(self.export_imc_btn)
        self.export_frames_btn = QPushButton("Export Frames...")
        self.export_frames_btn.clicked.connect(self._export_frames)
        action_row.addWidget(self.export_frames_btn)
        self.import_frame_btn = QPushButton("Import Frame PNG...")
        self.import_frame_btn.clicked.connect(self._import_frame_png)
        action_row.addWidget(self.import_frame_btn)
        self.replace_imc_btn = QPushButton("Replace IMC...")
        self.replace_imc_btn.clicked.connect(self._replace_imc)
        action_row.addWidget(self.replace_imc_btn)
        self.save_cat_btn = QPushButton("Save Catalog")
        self.save_cat_btn.clicked.connect(self._save_catalog)
        action_row.addWidget(self.save_cat_btn)
        self.save_frame_btn = QPushButton("Save Frame PNG...")
        self.save_frame_btn.clicked.connect(self._save_frame_png)
        action_row.addWidget(self.save_frame_btn)
        self.save_strip_btn = QPushButton("Save Contact Sheet...")
        self.save_strip_btn.clicked.connect(self._save_contact_sheet)
        action_row.addWidget(self.save_strip_btn)
        rlay.addLayout(action_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 760])

        self._set_controls_enabled(False)

    def set_dl_path(self, path: str):
        self.dl_path = path
        self._refresh_catalogs()

    def _set_controls_enabled(self, enabled: bool):
        self.prev_btn.setEnabled(enabled)
        self.play_btn.setEnabled(enabled)
        self.next_btn.setEnabled(enabled)
        self.frame_spin.setEnabled(enabled)
        self.zoom_combo.setEnabled(enabled)
        self.speed_combo.setEnabled(enabled)
        self.grid_check.setEnabled(enabled)
        self.export_imc_btn.setEnabled(enabled)
        self.export_frames_btn.setEnabled(enabled)
        self.import_frame_btn.setEnabled(enabled)
        self.replace_imc_btn.setEnabled(enabled)
        self.save_frame_btn.setEnabled(enabled)
        self.save_strip_btn.setEnabled(enabled)
        self.save_cat_btn.setEnabled(bool(self._selected_cat) and self._cat_dirty.get(self._selected_cat, False))
        if not enabled:
            self._play_timer.stop()
            self.play_btn.setText("Play")

    def _refresh_catalogs(self):
        self.cat_combo.blockSignals(True)
        self.cat_combo.clear()
        self._cat_entries = {}
        self._cat_dirty = {}
        if self.dl_path and os.path.isdir(self.dl_path):
            for cat_name in ("E00C.CAT", "M00C.CAT"):
                cat_path = os.path.join(self.dl_path, cat_name)
                if not os.path.isfile(cat_path):
                    continue
                try:
                    from darklands.extract_cat import readEntries
                    entries = [
                        entry for entry in readEntries(cat_path)
                        if entry['name'].upper().endswith('.IMC')
                    ]
                except Exception:
                    entries = []
                if entries:
                    self._cat_entries[cat_name] = entries
                    self._cat_dirty[cat_name] = False
                    self.cat_combo.addItem(f"{cat_name} ({len(entries)})", cat_name)
        self.cat_combo.blockSignals(False)
        if self.cat_combo.count():
            self.cat_combo.setCurrentIndex(0)
            self._on_cat_changed()
        else:
            self.entry_list.clear()
            self._frames = []
            self._frame_pixmaps = []
            self.thumb_list.clear()
            self._selected_cat = ""
            self._selected_entry = ""
            self._current_pixmap = None
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("No tactical catalogs found")
            self.info_label.setText("No IMC catalogs found in the selected Darklands folder.")
            self._set_controls_enabled(False)

    def _on_cat_changed(self):
        cat_name = self.cat_combo.currentData()
        self._selected_cat = cat_name or ""
        self.entry_list.clear()
        self._selected_entry = ""
        self.save_cat_btn.setEnabled(bool(self._selected_cat) and self._cat_dirty.get(self._selected_cat, False))
        entries = self._cat_entries.get(self._selected_cat, [])
        for entry in entries:
            self.entry_list.addItem(entry['name'])
        if self.entry_list.count():
            self.entry_list.setCurrentRow(0)
            self._on_entry_clicked(self.entry_list.item(0))
        else:
            self._frames = []
            self._frame_pixmaps = []
            self.thumb_list.clear()
            self._current_pixmap = None
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("No IMC entries")
            self.info_label.setText("This catalog has no IMC entries.")
            self._set_controls_enabled(False)

    def _on_entry_clicked(self, item: QListWidgetItem):
        self._selected_entry = item.text()
        self._reload_current_entry()

    def _reload_current_entry(self):
        if not self._selected_cat or not self._selected_entry:
            return
        try:
            from darklands.reader_imc import readDataBytes, render_rgba
            entries = self._cat_entries.get(self._selected_cat, [])
            entry = next((entry for entry in entries if entry['name'].upper() == self._selected_entry.upper()), None)
            if entry is None:
                return
            image_group = os.path.splitext(entry['name'])[0][:3].upper()
            current_choice = self.palette_combo.currentData()
            if current_choice == "default":
                from darklands.format_pic import default_pal
                palette = list(default_pal)
                enemy_type = None
                palette_note = "default VGA palette"
            else:
                auto_palette, enemy_type, auto_note, auto_selection = _enemy_palette_for_group(self.dl_path, image_group)
                self._refresh_palette_options(enemy_type, auto_selection)
                current_choice = self.palette_combo.currentData()
                if current_choice == "default":
                    from darklands.format_pic import default_pal
                    palette = list(default_pal)
                    enemy_type = None
                    palette_note = "default VGA palette"
                elif isinstance(current_choice, str) and current_choice.startswith("custom:"):
                    _, block_text, idx_text = current_choice.split(":", 2)
                    block = int(block_text)
                    idx = int(idx_text)
                    selection = {32: None, 48: None, 64: None}
                    selection.update(auto_selection)
                    selection[block] = idx
                    _, _, palette_chunks, base_palette = _load_enemy_preview_context(self.dl_path)
                    palette, palette_note = _build_enemy_palette(base_palette, palette_chunks, selection)
                else:
                    palette = auto_palette
                    palette_note = auto_note
            imc = readDataBytes(entry['data'], name=entry['name'])
            self._current_palette = list(palette)
            self._current_imc = imc
            self._frames = imc.get('frames', [])
            self._frame_pixmaps = []
            for frame in self._frames:
                rows = frame.get('rows', [])
                rgba, w, h = render_rgba(rows, palette)
                self._frame_pixmaps.append(_bytes_to_pixmap(rgba, w, h))
            self._rebuild_thumbnails()
            self._frame_idx = 0
            count = max(1, len(self._frame_pixmaps))
            self.frame_spin.blockSignals(True)
            self.frame_spin.setMaximum(count)
            self.frame_spin.setValue(1)
            self.frame_spin.blockSignals(False)
            self._set_controls_enabled(bool(self._frame_pixmaps))
            type_name = enemy_type.get('name', '') if enemy_type else ''
            dims = ""
            if self._frame_pixmaps:
                dims = f"{self._frame_pixmaps[0].width()}x{self._frame_pixmaps[0].height()}"
            self.info_label.setText(
                f"{self._selected_cat} / {entry['name']}\n"
                f"Image group: {image_group}"
                + (f"  ({type_name})" if type_name else "")
                + f"\nFrames: {len(self._frame_pixmaps)}"
                + (f"  First frame: {dims}" if dims else "")
                + f"\nPalette: {palette_note}"
            )
            self._apply_current_frame()
        except Exception:
            self._frames = []
            self._frame_pixmaps = []
            self.thumb_list.clear()
            self._current_pixmap = None
            self._current_palette = []
            self._current_imc = None
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText(f"Error:\n{traceback.format_exc()}")
            self.info_label.setText("Failed to decode IMC entry.")
            self._set_controls_enabled(False)

    def _refresh_palette_options(self, enemy_type, auto_selection):
        current = self.palette_combo.currentData()
        self.palette_combo.blockSignals(True)
        self.palette_combo.clear()
        self.palette_combo.addItem("Enemy palette (auto)", "auto")
        if enemy_type is not None:
            _, _, palette_chunks, _ = _load_enemy_preview_context(self.dl_path)
            pal_start = int(enemy_type.get("pal_start", 0))
            pal_cnt = max(1, int(enemy_type.get("pal_cnt", 0)))
            block_choices = {}
            for chunk in palette_chunks:
                idx = chunk.get("index", -1)
                if pal_start <= idx < pal_start + pal_cnt:
                    block = int(chunk.get("block_index", chunk.get("start_index", 64)))
                    block_choices.setdefault(block, []).append(idx)
            for block, indices in sorted(block_choices.items()):
                for idx in indices:
                    label = f"Block {block}-{block + 15}: palette #{idx}"
                    self.palette_combo.addItem(label, f"custom:{block}:{idx}")
        self.palette_combo.addItem("Default VGA", "default")
        restore_idx = self.palette_combo.findData(current)
        if restore_idx < 0:
            restore_idx = 0
        self.palette_combo.setCurrentIndex(restore_idx)
        self.palette_combo.blockSignals(False)

    def _apply_current_frame(self):
        if not self._frame_pixmaps:
            self._current_pixmap = None
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("No frame")
            self.play_btn.setText("Play")
            self._play_timer.stop()
            return
        self._current_pixmap = self._frame_pixmaps[self._frame_idx]
        self._apply_zoom()
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(self._frame_idx + 1)
        self.frame_spin.blockSignals(False)
        self._syncing_thumb = True
        self.thumb_list.setCurrentRow(self._frame_idx)
        self._syncing_thumb = False
        if self.thumb_list.currentItem() is not None:
            self.thumb_list.scrollToItem(self.thumb_list.currentItem())
        self.prev_btn.setEnabled(len(self._frame_pixmaps) > 1)
        self.next_btn.setEnabled(len(self._frame_pixmaps) > 1)

    def _prev_frame(self):
        if not self._frame_pixmaps:
            return
        self._frame_idx = (self._frame_idx - 1) % len(self._frame_pixmaps)
        self._apply_current_frame()

    def _next_frame(self):
        if not self._frame_pixmaps:
            return
        self._frame_idx = (self._frame_idx + 1) % len(self._frame_pixmaps)
        self._apply_current_frame()

    def _on_frame_spin(self, value: int):
        if not self._frame_pixmaps:
            return
        self._frame_idx = max(0, min(value - 1, len(self._frame_pixmaps) - 1))
        self._apply_current_frame()

    def _on_zoom_changed(self):
        self._zoom = float(self.zoom_combo.currentData() or 1.0)
        self._apply_zoom()

    def _on_speed_changed(self):
        self._play_timer.setInterval(int(self.speed_combo.currentData() or 120))

    def _rebuild_thumbnails(self):
        self._syncing_thumb = True
        self.thumb_list.clear()
        for idx, pm in enumerate(self._frame_pixmaps, start=1):
            thumb = pm.scaled(
                48, 48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            item = QListWidgetItem(QIcon(thumb), str(idx))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.thumb_list.addItem(item)
        self._syncing_thumb = False

    def _on_thumb_selected(self, row: int):
        if self._syncing_thumb or row < 0 or row >= len(self._frame_pixmaps):
            return
        self._frame_idx = row
        self._apply_current_frame()

    def eventFilter(self, obj, event):
        if (obj is self._scroll.viewport()
                and event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if event.angleDelta().y() > 0:
                self._bump_zoom(1)
            else:
                self._bump_zoom(-1)
            return True
        return super().eventFilter(obj, event)

    def _bump_zoom(self, direction: int):
        current = self.zoom_combo.currentIndex()
        target = max(0, min(self.zoom_combo.count() - 1, current + direction))
        if target != current:
            self.zoom_combo.setCurrentIndex(target)

    def _apply_zoom(self):
        if self._current_pixmap is None:
            return
        pm = self._current_pixmap
        if abs(self._zoom - 1.0) < 1e-9:
            scaled = pm
        else:
            w = max(1, int(pm.width() * self._zoom))
            h = max(1, int(pm.height() * self._zoom))
            scaled = pm.scaled(
                w, h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        if self.grid_check.isChecked() and self._zoom >= 4.0 and not scaled.isNull():
            overlay = QPixmap(scaled)
            painter = QPainter(overlay)
            pen = QPen(QColor(255, 255, 255, 70))
            pen.setWidth(1)
            painter.setPen(pen)
            step = max(1, int(round(self._zoom)))
            for x in range(0, overlay.width() + 1, step):
                painter.drawLine(x, 0, x, overlay.height())
            for y in range(0, overlay.height() + 1, step):
                painter.drawLine(0, y, overlay.width(), y)
            painter.end()
            scaled = overlay
        self._image_label.setPixmap(scaled)
        self._image_label.resize(scaled.size())
        self._image_label.setMinimumSize(scaled.size())
        self._image_host.adjustSize()

    def _save_frame_png(self):
        if self._current_pixmap is None or not self._selected_entry:
            return
        suggested = f"{os.path.splitext(self._selected_entry)[0]}_frame{self._frame_idx + 1:03d}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Frame PNG", suggested, "PNG Images (*.png);;All Files (*)"
        )
        if path:
            self._current_pixmap.save(path)

    def _save_contact_sheet(self):
        if not self._frame_pixmaps or not self._selected_entry:
            return
        cell_w = max(pm.width() for pm in self._frame_pixmaps)
        cell_h = max(pm.height() for pm in self._frame_pixmaps)
        cols = min(8, max(1, len(self._frame_pixmaps)))
        rows = (len(self._frame_pixmaps) + cols - 1) // cols
        sheet = QPixmap(cell_w * cols, cell_h * rows)
        sheet.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QPainter
        painter = QPainter(sheet)
        for idx, pm in enumerate(self._frame_pixmaps):
            x = (idx % cols) * cell_w
            y = (idx // cols) * cell_h
            painter.drawPixmap(x, y, pm)
        painter.end()
        suggested = f"{os.path.splitext(self._selected_entry)[0]}_sheet.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Contact Sheet", suggested, "PNG Images (*.png);;All Files (*)"
        )
        if path:
            sheet.save(path)

    def _toggle_playback(self):
        if not self._frame_pixmaps:
            return
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.play_btn.setText("Play")
        else:
            self._play_timer.start()
            self.play_btn.setText("Stop")

    def _export_frames(self):
        if not self._frame_pixmaps or not self._selected_entry:
            return
        target_dir = QFileDialog.getExistingDirectory(
            self, "Export IMC Frames", self.dl_path or ""
        )
        if not target_dir:
            return
        stem = os.path.splitext(self._selected_entry)[0]
        written = 0
        for idx, pm in enumerate(self._frame_pixmaps, start=1):
            out_path = os.path.join(target_dir, f"{stem}_frame{idx:03d}.png")
            if pm.save(out_path):
                written += 1
        self.info_label.setText(self.info_label.text() + f"\nExported {written} frame PNG(s).")

    def _import_frame_png(self):
        entry = self._current_entry_dict()
        if entry is None or not self._current_imc or not self._current_palette or not self._frames:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Frame PNG", self.dl_path or "", "PNG Images (*.png);;All Files (*)"
        )
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.critical(self, "Import error", "Could not read the selected PNG file.")
            return
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
        old_rows = self._frames[self._frame_idx].get("rows", [])
        expected_h = len(old_rows)
        expected_w = max((len(row) for row in old_rows), default=0)
        if image.width() != expected_w or image.height() != expected_h:
            QMessageBox.critical(
                self,
                "Import error",
                f"Frame size mismatch. Expected {expected_w}x{expected_h}, got {image.width()}x{image.height()}.",
            )
            return

        palette_map = {}
        candidates = []
        for idx, color in enumerate(self._current_palette):
            if color is None:
                continue
            palette_map.setdefault(tuple(color), idx)
            candidates.append((idx, color))

        rows = []
        for y in range(image.height()):
            row = []
            for x in range(image.width()):
                rgba = image.pixelColor(x, y)
                if rgba.alpha() < 32:
                    row.append(0)
                    continue
                rgb = (rgba.red(), rgba.green(), rgba.blue())
                idx = palette_map.get(rgb)
                if idx is None:
                    idx = min(
                        candidates,
                        key=lambda item: (
                            (item[1][0] - rgb[0]) ** 2
                            + (item[1][1] - rgb[1]) ** 2
                            + (item[1][2] - rgb[2]) ** 2
                        ),
                    )[0] if candidates else 0
                row.append(idx)
            rows.append(row)

        try:
            from darklands.reader_imc import writeDataBytes
            self._current_imc['frames'][self._frame_idx]['rows'] = rows
            entry['data'] = writeDataBytes(self._current_imc, name=entry['name'])
            self._cat_dirty[self._selected_cat] = True
            self.save_cat_btn.setEnabled(True)
            self._reload_current_entry()
            self.info_label.setText(self.info_label.text() + "\nUnsaved catalog change: imported current frame PNG.")
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))


    def _current_entry_dict(self):
        if not self._selected_cat or not self._selected_entry:
            return None
        entries = self._cat_entries.get(self._selected_cat, [])
        return next((entry for entry in entries if entry['name'].upper() == self._selected_entry.upper()), None)

    def _export_imc(self):
        entry = self._current_entry_dict()
        if entry is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export IMC", entry['name'], "IMC Files (*.IMC);;All Files (*)"
        )
        if path:
            with open(path, 'wb') as fh:
                fh.write(entry.get('data', b''))

    def _replace_imc(self):
        entry = self._current_entry_dict()
        if entry is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Replace IMC", self.dl_path or "", "IMC Files (*.IMC);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, 'rb') as fh:
                entry['data'] = fh.read()
            self._cat_dirty[self._selected_cat] = True
            self._reload_current_entry()
            self.info_label.setText(self.info_label.text() + "\nUnsaved catalog change: replaced current IMC.")
            self.save_cat_btn.setEnabled(True)
        except OSError as exc:
            QMessageBox.critical(self, "Replace error", str(exc))

    def _save_catalog(self):
        if not self._selected_cat or not self.dl_path:
            return
        try:
            from darklands.extract_cat import writeCat
            path = os.path.join(self.dl_path, self._selected_cat)
            writeCat(path, self._cat_entries.get(self._selected_cat, []))
            self._cat_dirty[self._selected_cat] = False
            self.save_cat_btn.setEnabled(False)
            self.info_label.setText(self.info_label.text() + "\nCatalog saved.")
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))


# ---------------------------------------------------------------------------
# DRLE decompressor — browse button auto-triggers load
# ---------------------------------------------------------------------------

class DrleConverter(ConverterWidget):
    _auto_on_path = False  # file-picker, not DL-path based

    def __init__(self, parent=None):
        super().__init__("DRLE Decompressor", parent)

        row = QHBoxLayout()
        row.addWidget(QLabel("Input File:"))
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Select a DRLE-compressed file…")
        row.addWidget(self.file_edit)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row.addWidget(b)
        self.input_layout.addLayout(row)

        self._decompressed: bytes | None = None
        copy_btn = QPushButton("Copy Summary")
        copy_btn.clicked.connect(self._copy_summary)
        self.action_layout.addWidget(copy_btn)

        save_raw_btn = QPushButton("Save Decompressed…")
        save_raw_btn.clicked.connect(self._save_raw)
        self.action_layout.addWidget(save_raw_btn)

    def _build_output_widget(self):
        self._hex_view = HexView()
        return self._hex_view

    def _browse(self):
        start = self.dl_path or ""
        path, _ = QFileDialog.getOpenFileName(self, "Open File", start, "All Files (*)")
        if path:
            self.file_edit.setText(path)
            self._load(path)

    def run(self):
        fname = self.file_edit.text()
        if fname:
            self._load(fname)

    def _load(self, fname: str):
        if not os.path.isfile(fname):
            self._show_error(f"File not found:\n{fname}")
            return
        try:
            from darklands.reader_drle import readFile
            result = readFile(fname)
            self._decompressed = bytes(result)
            self._summary_text = (
                f"Decompressed {len(result):,} bytes from {os.path.basename(fname)}\n"
                f"Path: {fname}"
            )
            self._hex_view.set_bytes(self._decompressed, header=self._summary_text, max_rows=128)
        except Exception:
            self._show_error(traceback.format_exc())

    def _show_error(self, msg: str):
        self._hex_view.set_message(f"Error:\n{msg}")

    def _copy_summary(self):
        if not getattr(self, "_summary_text", ""):
            return
        QApplication.clipboard().setText(self._summary_text)

    def _save_raw(self):
        if self._decompressed is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Decompressed", "", "All Files (*)"
        )
        if path:
            with open(path, 'wb') as f:
                f.write(self._decompressed)
