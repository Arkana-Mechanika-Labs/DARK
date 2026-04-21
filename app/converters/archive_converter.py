"""
Archive converter: three-pane CAT browser with inline preview.

  Pane 1 (narrow)  : .CAT files in the game folder
  Pane 2 (medium)  : files inside the selected CAT  (multi-select for extraction)
  Pane 3 (wide)    : vertical split
      Top           : preview  — image (PIC) or hex dump (everything else)
      Bottom        : extraction log

Clicking a file in pane 2 auto-previews it.
"Extract Selected" / "Extract All" ask for an output directory.
"""
import os
import tempfile
import traceback
from functools import lru_cache
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QSplitter, QListWidget, QListWidgetItem, QPlainTextEdit,
    QFrame, QScrollArea, QSizePolicy, QApplication, QStackedWidget,
    QMessageBox,
)
from PySide6.QtGui import QColor, QFont, QPixmap, QImage
from PySide6.QtCore import Qt
from app.file_ops import backup_existing_file, backup_label
from app.format_coverage import classify_name
from app.widgets.hex_view import HexView


# ---------------------------------------------------------------------------
# Preview helpers
# ---------------------------------------------------------------------------

def _hex_dump(data: bytes, max_bytes: int = 512) -> str:
    COLS = 16
    lines = [f"Binary  ({len(data):,} bytes total)\n"]
    for i in range(0, min(len(data), max_bytes), COLS):
        chunk = data[i:i + COLS]
        hex_  = ' '.join(f'{b:02X}' for b in chunk)
        asc   = ''.join(chr(b) if 0x20 <= b < 0x7f else '.' for b in chunk)
        lines.append(f'{i:06X}  {hex_:<{COLS * 3 - 1}}  {asc}')
    if len(data) > max_bytes:
        lines.append(f'\n… {len(data) - max_bytes:,} more bytes (extract to see all)')
    return '\n'.join(lines)


def _try_pic_pixmap(data: bytes) -> QPixmap | None:
    """Try to decode raw bytes as a Darklands PIC and return a QPixmap, or None."""
    try:
        import io, tempfile
        from darklands.format_pic import Pic, default_pal
        # Pic needs a real file path; write to a temp file
        with tempfile.NamedTemporaryFile(suffix='.PIC', delete=False) as tf:
            tf.write(data)
            tmp_path = tf.name
        try:
            pic = Pic(tmp_path)
            if not pic.pal:
                pic.pal = list(default_pal)
            if not pic.pic:
                return None
            rgba, w, h = pic.render_rgba_bytes()
            img = QImage(rgba, w, h, QImage.Format.Format_ARGB32)
            return QPixmap.fromImage(img)
        finally:
            os.unlink(tmp_path)
    except Exception:
        return None


@lru_cache(maxsize=8)
def _load_enemy_preview_context(dl_path: str):
    from darklands.reader_enemypal import readData as read_enemy_palettes
    from darklands.reader_enm import readData as read_enemies
    from darklands.palette_context import load_combat_palette

    enemy_types, _ = read_enemies(dl_path)
    palette_chunks = read_enemy_palettes(dl_path)
    return enemy_types, palette_chunks, load_combat_palette(dl_path)


def _enemy_imc_palette(dl_path: str, cat_file: str, entry_name: str):
    from darklands.palette_context import load_combat_palette

    if not dl_path:
        return load_combat_palette(dl_path), "combat base palette"
    if os.path.basename(cat_file).upper() not in {"E00C.CAT", "M00C.CAT"}:
        return load_combat_palette(dl_path), "combat base palette"

    image_group = os.path.splitext(entry_name)[0].upper()[:3]
    try:
        enemy_types, palette_chunks, base_palette = _load_enemy_preview_context(dl_path)
    except Exception:
        return load_combat_palette(dl_path), "combat base palette"

    enemy_type = next(
        (et for et in enemy_types if et.get("image_group", "").upper() == image_group),
        None,
    )
    if enemy_type is None:
        return list(base_palette), "combat base palette"

    pal_start = enemy_type.get("pal_start", 0)
    pal_cnt = max(1, enemy_type.get("pal_cnt", 0))
    matching = [
        chunk for chunk in palette_chunks
        if pal_start <= chunk.get("index", -1) < pal_start + pal_cnt
    ]
    palette = list(base_palette)
    if matching:
        digits = "".join(ch for ch in str(enemy_type.get("name", "")) if ch.isdigit())
        chunk = matching[0]
        if digits:
            variant_idx = max(0, min(int(digits) - 1, len(matching) - 1))
            chunk = matching[variant_idx]
        start = chunk.get("start_index", 0)
        for offset, color in enumerate(chunk.get("colors", [])):
            slot = start + offset
            if 0 <= slot < len(palette):
                palette[slot] = color
        return palette, f"{enemy_type.get('name', image_group)} ({image_group}, block {start}-{start + 15}, palette #{chunk.get('index', 0)})"
    return palette, f"{enemy_type.get('name', image_group)} ({image_group})"


def _try_imc_pixmap(data: bytes, entry_name: str, cat_file: str = "", dl_path: str = ""):
    try:
        from darklands.reader_imc import readDataBytes, render_rgba

        imc = readDataBytes(data, name=entry_name)
        frames = imc.get("frames", [])
        if not frames:
            return None, None
        rows = frames[0].get("rows", [])
        if not rows:
            return None, None
        palette, palette_label = _enemy_imc_palette(dl_path, cat_file, entry_name)
        rgba, w, h = render_rgba(rows, palette)
        img = QImage(rgba, w, h, QImage.Format.Format_ARGB32)
        return QPixmap.fromImage(img), f"{entry_name}  ({w}x{h}, {len(frames)} frame(s), palette: {palette_label})"
    except Exception:
        return None, None


def _render_msg_cards(data: bytes) -> str | None:
    try:
        from darklands.reader_msg import readDataBytes
        cards = readDataBytes(data)
    except Exception:
        return None
    lines = [f"Dialog cards: {len(cards)}", ""]
    for idx, card in enumerate(cards):
        lines.append(
            f"--- Card {idx} "
            f"(y={card.get('textOffsY', 0)} x={card.get('textOffsX', 0)} "
            f"maxX={card.get('textMaxX', 0)}) ---"
        )
        for element in card.get('elements', []):
            if isinstance(element, str):
                lines.append(element)
            elif isinstance(element, (list, tuple)) and element:
                kind = element[0]
                dots = element[1] if len(element) > 1 else ''
                label = element[2] if len(element) > 2 else ''
                if label:
                    lines.append(f"[{kind}] {dots} -> {label}".rstrip())
                elif dots:
                    lines.append(f"[{kind}] {dots}")
                else:
                    lines.append(f"[{kind}]")
        lines.append("")
    return "\n".join(lines)


# Extension → preview strategy
_TEXT_EXTS  = {'.TXT', '.CFG', '.INI', '.BAT', '.LOG'}
_IMAGE_EXTS = {'.PIC'}
_IMC_EXTS = {'.IMC'}
_MSG_EXTS = {'.MSG'}
_CAT_FAMILY = {'.CAT', 'MSGFILES', 'BC', 'LCASTLE'}


class _PreviewWidget(QStackedWidget):
    """
    Page 0 — image (QScrollArea + QLabel)
    Page 1 — text  (QPlainTextEdit)
    Page 2 — hex   (HexView)
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # Page 0: image
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        self._img_label = QLabel()
        self._img_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        scroll.setWidget(self._img_label)
        self.addWidget(scroll)   # index 0

        # Page 1: text / hex
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Courier New", 9))
        self.addWidget(self._text)  # index 1

        self._hex = HexView()
        self.addWidget(self._hex)  # index 2

        self.show_placeholder()

    def show_placeholder(self):
        self._text.setPlainText("Click a file in the contents list to preview it…")
        self.setCurrentIndex(1)

    def show_image(self, pixmap: QPixmap, label: str = ""):
        self._img_label.setPixmap(pixmap)
        self._img_label.resize(pixmap.size())
        self._img_label.setToolTip(label)
        self.setCurrentIndex(0)

    def show_text(self, text: str):
        self._text.setPlainText(text)
        self.setCurrentIndex(1)

    def show_hex(self, data: bytes, header: str = "", max_rows: int | None = None):
        self._hex.set_bytes(data, header=header, max_rows=max_rows)
        self.setCurrentIndex(2)


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class CatConverter(QWidget):
    """CAT archive browser — folder list → contents list → preview + log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._cat_file: str = ""
        self._entries: list[tuple[str, int, int]] = []   # (name, size, offset)
        self._entry_data: list[dict] = []
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # ── Title ─────────────────────────────────────────────────────────
        title = QLabel("CAT Archive Browser")
        f = title.font(); f.setPointSize(11); f.setBold(True); title.setFont(f)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # ── Folder picker row ─────────────────────────────────────────────
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Folder:"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder containing .CAT files…")
        self.folder_edit.setReadOnly(True)
        folder_row.addWidget(self.folder_edit)
        browse_folder_btn = QPushButton("…")
        browse_folder_btn.setFixedWidth(28)
        browse_folder_btn.setToolTip("Browse for a folder containing .CAT files")
        browse_folder_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_folder_btn)
        root.addLayout(folder_row)

        # ── Three-pane splitter ───────────────────────────────────────────
        outer = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(outer, stretch=1)

        # Pane 1 — CAT file list
        pane1 = QWidget()
        pane1.setMinimumWidth(110)
        pane1.setMaximumWidth(190)
        p1lay = QVBoxLayout(pane1)
        p1lay.setContentsMargins(0, 0, 4, 0)
        p1lay.setSpacing(3)
        p1lay.addWidget(QLabel("CAT files:"))
        self._cat_filter = QLineEdit()
        self._cat_filter.setPlaceholderText("Filter CAT files...")
        self._cat_filter.textChanged.connect(self._apply_cat_filter)
        p1lay.addWidget(self._cat_filter)
        self.cat_list = QListWidget()
        self.cat_list.itemClicked.connect(self._on_cat_clicked)
        p1lay.addWidget(self.cat_list)
        outer.addWidget(pane1)

        # Pane 2 — contents of selected CAT
        pane2 = QWidget()
        pane2.setMinimumWidth(130)
        pane2.setMaximumWidth(230)
        p2lay = QVBoxLayout(pane2)
        p2lay.setContentsMargins(4, 0, 4, 0)
        p2lay.setSpacing(3)
        self.contents_label = QLabel("Contents:")
        p2lay.addWidget(self.contents_label)
        self._entry_filter = QLineEdit()
        self._entry_filter.setPlaceholderText("Filter entries...")
        self._entry_filter.textChanged.connect(self._apply_entry_filter)
        p2lay.addWidget(self._entry_filter)
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.file_list.itemClicked.connect(self._on_entry_clicked)
        self.file_list.itemSelectionChanged.connect(self._on_selection_changed)
        p2lay.addWidget(self.file_list)
        outer.addWidget(pane2)

        # Pane 3 — vertical split: preview (top) + log (bottom)
        right_split = QSplitter(Qt.Orientation.Vertical)

        self._preview = _PreviewWidget()
        right_split.addWidget(self._preview)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Courier New", 9))
        self._log.setPlaceholderText("Extraction results will appear here…")
        self._log.setMaximumHeight(160)
        self._log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        right_split.addWidget(self._log)

        right_split.setStretchFactor(0, 1)
        right_split.setStretchFactor(1, 0)
        right_split.setSizes([500, 140])

        outer.addWidget(right_split)

        outer.setStretchFactor(0, 0)
        outer.setStretchFactor(1, 0)
        outer.setStretchFactor(2, 1)
        outer.setSizes([150, 190, 560])

        # ── Action bar ────────────────────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.addStretch()

        self.extract_sel_btn = QPushButton("Extract Selected…")
        self.extract_sel_btn.setToolTip(
            "Extract the highlighted file(s) to a chosen directory"
        )
        self.extract_sel_btn.setEnabled(False)
        self.extract_sel_btn.clicked.connect(self._extract_selected)
        action_row.addWidget(self.extract_sel_btn)

        self.extract_all_btn = QPushButton("Extract All…")
        self.extract_all_btn.setToolTip("Extract every file in the CAT archive")
        self.extract_all_btn.setEnabled(False)
        self.extract_all_btn.clicked.connect(self._extract_all)
        action_row.addWidget(self.extract_all_btn)

        self.replace_btn = QPushButton("Replace Selected...")
        self.replace_btn.setEnabled(False)
        self.replace_btn.clicked.connect(self._replace_selected)
        action_row.addWidget(self.replace_btn)

        self.open_tool_btn = QPushButton("Open in Tool")
        self.open_tool_btn.setEnabled(False)
        self.open_tool_btn.clicked.connect(self._open_in_tool)
        action_row.addWidget(self.open_tool_btn)

        self.add_btn = QPushButton("Add Files...")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add_files)
        action_row.addWidget(self.add_btn)

        self.save_btn = QPushButton("Save CAT")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_cat)
        action_row.addWidget(self.save_btn)

        self.save_as_btn = QPushButton("Save CAT As...")
        self.save_as_btn.setEnabled(False)
        self.save_as_btn.clicked.connect(self._save_cat_as)
        action_row.addWidget(self.save_as_btn)

        copy_btn = QPushButton("Copy Log")
        copy_btn.setFixedWidth(80)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self._log.toPlainText())
        )
        action_row.addWidget(copy_btn)

        root.addLayout(action_row)

    def _apply_entry_coverage(self, item: QListWidgetItem, entry_name: str):
        coverage = classify_name(entry_name)
        item.setData(Qt.ItemDataRole.UserRole, coverage)
        tooltip = [entry_name]
        prior = item.toolTip().strip()
        if prior:
            tooltip.append(prior)
        tooltip.extend([
            f"Status: {coverage.status_label}",
            f"Family: {coverage.family}",
        ])
        if coverage.editor_title:
            tooltip.append(f"Editor: {coverage.editor_title}")
        if coverage.kb_doc:
            tooltip.append(f"KB: {coverage.kb_doc}")
        if coverage.notes:
            tooltip.append("")
            tooltip.append(coverage.notes)
        item.setToolTip("\n".join(tooltip))
        color_map = {
            "editable": "#63c174",
            "supported": "#6daae0",
            "wip": "#d6a553",
            "runtime": "#9da8b5",
            "unknown": "#c8c8c8",
        }
        item.setForeground(QColor(color_map.get(coverage.status, "#c8c8c8")))

    # ── DL path / folder management ───────────────────────────────────────

    def set_dl_path(self, path: str):
        if path == self.dl_path:
            return
        self.dl_path = path
        if path:
            self.folder_edit.setText(path)
            self._refresh_cat_list(path)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Folder with CAT Files",
            self.folder_edit.text() or self.dl_path or ""
        )
        if path:
            self.folder_edit.setText(path)
            self._refresh_cat_list(path)

    def _refresh_cat_list(self, folder: str):
        self.cat_list.clear()
        self._clear_contents()
        if not folder or not os.path.isdir(folder):
            return
        files = sorted(
            f for f in os.listdir(folder)
            if f.upper().endswith('.CAT') or f.upper() in _CAT_FAMILY
        )
        for fname in files:
            self.cat_list.addItem(fname)
        self._apply_cat_filter()

    def focus_filter(self):
        self._cat_filter.setFocus()
        self._cat_filter.selectAll()

    def _apply_cat_filter(self):
        needle = self._cat_filter.text().strip().lower()
        first_visible = -1
        for row in range(self.cat_list.count()):
            item = self.cat_list.item(row)
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = row
        current = self.cat_list.currentRow()
        if current >= 0 and self.cat_list.item(current).isHidden() and first_visible >= 0:
            self.cat_list.setCurrentRow(first_visible)

    def _apply_entry_filter(self):
        needle = self._entry_filter.text().strip().lower()
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

    # ── CAT selection ─────────────────────────────────────────────────────

    def _on_cat_clicked(self, item: QListWidgetItem):
        folder = self.folder_edit.text() or self.dl_path
        if not folder:
            return
        self._load_cat(os.path.join(folder, item.text()))

    def _clear_contents(self):
        self.file_list.clear()
        self._entries = []
        self._entry_data = []
        self._cat_file = ""
        self._dirty = False
        self.contents_label.setText("Contents:")
        self.extract_all_btn.setEnabled(False)
        self.extract_sel_btn.setEnabled(False)
        self.replace_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.save_as_btn.setEnabled(False)
        self._preview.show_placeholder()

    def _load_cat(self, fname: str):
        self._clear_contents()
        if not os.path.isfile(fname):
            self._log.setPlainText(f"File not found:\n{fname}")
            return
        try:
            from darklands.extract_cat import readEntries
            self._entry_data = readEntries(fname)
            entries = [
                (entry['name'], len(entry.get('data', b'')), entry.get('offset', 0))
                for entry in self._entry_data
            ]
            self._entries = entries
            self._cat_file = fname

            self.contents_label.setText(f"Contents ({len(entries)}):")
            for fn, size, offs in entries:
                item = QListWidgetItem(fn)
                item.setToolTip(f"{size:,} bytes  @  offset {offs:,}")
                self._apply_entry_coverage(item, fn)
                self.file_list.addItem(item)

            total = sum(s for _, s, _ in entries)
            lines = [
                f"Contents of {os.path.basename(fname)} — {len(entries)} file(s)\n",
                f"{'Filename':<20}  {'Size':>10}  {'Offset':>10}",
                "-" * 46,
            ]
            for fn, size, offs in entries:
                lines.append(f"{fn:<20}  {size:>10,}  {offs:>10,}")
            lines += ["-" * 46, f"{'Total':<20}  {total:>10,}"]
            self._log.setPlainText("\n".join(lines))

            self.extract_all_btn.setEnabled(True)
            self.add_btn.setEnabled(True)
            self.save_as_btn.setEnabled(True)
        except Exception:
            self._log.setPlainText(traceback.format_exc())

    # ── Entry click → preview ─────────────────────────────────────────────

    def _on_entry_clicked(self, item: QListWidgetItem):
        if not self._cat_file:
            return
        entry_name = item.text()
        coverage = item.data(Qt.ItemDataRole.UserRole)
        ext = os.path.splitext(entry_name)[1].upper()
        try:
            from darklands.extract_cat import extractOneToBytes
            _, data = extractOneToBytes(self._cat_file, entry_name)
        except Exception:
            self._preview.show_text(traceback.format_exc())
            return

        coverage_prefix = ""
        if coverage is not None:
            coverage_prefix = (
                f"{entry_name}\n"
                f"Status: {coverage.status_label}\n"
                f"Family: {coverage.family}\n"
                f"Editor: {coverage.editor_title or '(none)'}\n"
                + (f"KB: {coverage.kb_doc}\n" if coverage.kb_doc else "")
                + "\n"
            )

        if ext in _IMAGE_EXTS:
            pixmap = _try_pic_pixmap(data)
            if pixmap is not None:
                self._preview.show_image(
                    pixmap,
                    f"{entry_name}  ({pixmap.width()}x{pixmap.height()})"
                    + (f"  •  {coverage.status_label}" if coverage is not None else "")
                )
                return
            # fall through to hex if decode failed

        if ext in _IMC_EXTS:
            pixmap, label = _try_imc_pixmap(data, entry_name, self._cat_file, self.dl_path)
            if pixmap is not None:
                display = label or entry_name
                if coverage is not None:
                    display += f"  •  {coverage.status_label}"
                self._preview.show_image(pixmap, display)
                return

        if ext in _MSG_EXTS:
            rendered = _render_msg_cards(data)
            if rendered:
                self._preview.show_text(coverage_prefix + rendered)
                return

        if ext in _TEXT_EXTS:
            try:
                self._preview.show_text(coverage_prefix + data.decode('latin-1'))
                return
            except Exception:
                pass

        # Default: structured hex view
        self._preview.show_hex(data, header=coverage_prefix.strip(), max_rows=128)

    def _on_selection_changed(self):
        has_sel = len(self.file_list.selectedItems()) > 0
        self.extract_sel_btn.setEnabled(has_sel and bool(self._cat_file))
        self.replace_btn.setEnabled(has_sel and bool(self._cat_file))
        self.open_tool_btn.setEnabled(self._selected_entry_target() is not None)

    def _set_dirty(self, message: str):
        self._dirty = True
        self.save_btn.setEnabled(bool(self._cat_file))
        self.save_as_btn.setEnabled(bool(self._cat_file))
        self._log.setPlainText(message)

    def _selected_entry_target(self):
        items = self.file_list.selectedItems()
        if len(items) != 1 or not self._cat_file:
            return None
        item = items[0]
        coverage = item.data(Qt.ItemDataRole.UserRole)
        if coverage is None or not coverage.editor_title or coverage.editor_title == "CAT Extractor":
            return None
        return item.text(), coverage

    def _entry_bytes(self, entry_name: str) -> bytes:
        from darklands.extract_cat import extractOneToBytes
        _name, data = extractOneToBytes(self._cat_file, entry_name)
        return data

    def _open_in_tool(self):
        target = self._selected_entry_target()
        if target is None:
            return
        entry_name, coverage = target
        try:
            data = self._entry_bytes(entry_name)
        except Exception as exc:
            QMessageBox.critical(self, "Open in Tool", f"Could not extract {entry_name} from the archive.\n\n{exc}")
            return
        main_window = self.window()
        opener = getattr(main_window, "open_archive_entry", None)
        if not callable(opener):
            QMessageBox.information(self, "Open in Tool", "This DARK window cannot route archive entries to another tool.")
            return
        if opener(coverage.editor_title, self._cat_file, entry_name, data):
            self._log.setPlainText(
                f"Opened {entry_name} in {coverage.editor_title}.\n"
                f"Source archive: {self._cat_file}"
            )
        else:
            QMessageBox.information(
                self,
                "Open in Tool",
                f"{entry_name} could not be opened in {coverage.editor_title} from this archive."
            )

    def _refresh_contents_view(self, select_name: str | None = None):
        self.file_list.clear()
        self._entries = []
        for entry in self._entry_data:
            data = entry.get('data', b'')
            item = QListWidgetItem(entry['name'])
            self._apply_entry_coverage(item, entry['name'])
            self.file_list.addItem(item)
            self._entries.append((entry['name'], len(data), entry.get('offset', 0)))
        self.contents_label.setText(f"Contents ({len(self._entry_data)}):")
        if select_name:
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                if item.text().upper() == select_name.upper():
                    self.file_list.setCurrentItem(item)
                    break
        self._apply_entry_filter()

    def _replace_selected(self):
        if not self._entry_data:
            return
        selected = [item.text() for item in self.file_list.selectedItems()]
        if not selected:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select replacement file(s)",
            self.dl_path or os.path.dirname(self._cat_file),
            "All Files (*)",
        )
        if not files:
            return
        replacements = {os.path.basename(path).upper(): path for path in files}
        changed = []
        for entry in self._entry_data:
            name_upper = entry['name'].upper()
            if name_upper in {s.upper() for s in selected}:
                if name_upper in replacements:
                    with open(replacements[name_upper], 'rb') as fh:
                        entry['data'] = fh.read()
                    changed.append(entry['name'])
        if not changed:
            QMessageBox.information(
                self,
                "No replacements",
                "Choose replacement files with the same names as the selected CAT entries.",
            )
            return
        self._refresh_contents_view(changed[0])
        self._set_dirty(
            "Replaced entries:\n\n" + "\n".join(changed)
        )

    def _add_files(self):
        if not self._cat_file:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select file(s) to add to CAT",
            self.dl_path or os.path.dirname(self._cat_file),
            "All Files (*)",
        )
        if not files:
            return
        changed = []
        by_name = {entry['name'].upper(): entry for entry in self._entry_data}
        for path in files:
            name = os.path.basename(path)[:12]
            with open(path, 'rb') as fh:
                data = fh.read()
            existing = by_name.get(name.upper())
            if existing is not None:
                existing['data'] = data
                changed.append(f"replaced {name}")
            else:
                self._entry_data.append({
                    'name': name,
                    'timestamp': b'\x00\x00\x00\x00',
                    'data': data,
                    'offset': 0,
                })
                by_name[name.upper()] = self._entry_data[-1]
                changed.append(f"added {name}")
        self._refresh_contents_view(os.path.basename(files[-1])[:12])
        self._set_dirty("Updated CAT entries:\n\n" + "\n".join(changed))

    def _write_cat_to(self, path: str):
        from darklands.extract_cat import writeCat
        backup = backup_existing_file(path)
        writeCat(path, self._entry_data)
        self._dirty = False
        self.save_btn.setEnabled(False)
        self.save_as_btn.setEnabled(True)
        self._log.setPlainText(f"Saved CAT archive:\n{path}\nBackup: {backup_label(backup)}")

    def _save_cat(self):
        if not self._cat_file:
            return
        try:
            self._write_cat_to(self._cat_file)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))

    def _save_cat_as(self):
        if not self._cat_file:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CAT As",
            self._cat_file,
            "CAT Files (*.CAT);;All Files (*)",
        )
        if not path:
            return
        try:
            self._write_cat_to(path)
            self._cat_file = path
            self.save_btn.setEnabled(False)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))

    # ── extraction ────────────────────────────────────────────────────────

    def _pick_output_dir(self) -> str | None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory",
            os.path.dirname(self._cat_file) if self._cat_file else ""
        )
        return path or None

    def _extract_selected(self):
        if not self._cat_file:
            return
        selected_names = [item.text() for item in self.file_list.selectedItems()]
        if not selected_names:
            return
        out_dir = self._pick_output_dir()
        if not out_dir:
            return
        try:
            from darklands.extract_cat import extractOne
            lines = [
                f"Extracted {len(selected_names)} file(s) → {out_dir}\n",
                f"{'Filename':<20}  {'Size':>10}",
                "-" * 34,
            ]
            total = 0
            for name in selected_names:
                _, size = extractOne(self._cat_file, name, out_dir)
                lines.append(f"{name:<20}  {size:>10,} bytes")
                total += size
            lines += ["-" * 34, f"{'Total':<20}  {total:>10,} bytes"]
            self._log.setPlainText("\n".join(lines))
        except Exception:
            self._log.setPlainText(traceback.format_exc())

    def _extract_all(self):
        if not self._cat_file:
            return
        out_dir = self._pick_output_dir()
        if not out_dir:
            return
        try:
            from darklands.extract_cat import extractAll
            files = extractAll(self._cat_file, out_dir)
            lines = [
                f"Extracted {len(files)} file(s) → {out_dir}\n",
                f"{'Filename':<20}  {'Size':>10}",
                "-" * 34,
            ]
            for fn, size in files:
                lines.append(f"{fn:<20}  {size:>10,} bytes")
            lines += [
                "-" * 34,
                f"{'Total':<20}  {sum(s for _, s in files):>10,} bytes",
            ]
            self._log.setPlainText("\n".join(lines))
        except Exception:
            self._log.setPlainText(traceback.format_exc())
