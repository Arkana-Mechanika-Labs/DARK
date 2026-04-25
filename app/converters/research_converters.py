import fnmatch
import os
import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QComboBox, QSpinBox, QScrollArea, QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt, QEvent, QTimer, QSize
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

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
    _ZOOM_STEPS = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.dl_path = ""
        self._files: list[str] = []
        self._selected_file = ""
        self._sequence = None
        self._frame_pixmaps: list[QPixmap] = []
        self._frame_idx = 0
        self._zoom = 2.0
        self._syncing_thumb = False
        self._autoload_first_on_show = False
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(83)
        self._play_timer.timeout.connect(self._next_frame)
        self._build_pan_ui()

    def _build_pan_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        title = QLabel("PAN Sequence Player")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self._summary = QLabel(
            "Browse and play decoded Darklands PAN presentation sequences with their embedded VGA palettes."
        )
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        left = QWidget()
        left.setMinimumWidth(180)
        left.setMaximumWidth(300)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(4)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter PAN files...")
        self._filter.textChanged.connect(self._apply_filter)
        left_layout.addWidget(self._filter)
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_file_clicked)
        left_layout.addWidget(self._list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)

        self.info_label = QLabel("Select a PAN file from the list.")
        self.info_label.setWordWrap(True)
        right_layout.addWidget(self.info_label)

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
        self.zoom_combo.setCurrentText("200%")
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        nav_row.addWidget(self.zoom_combo)
        nav_row.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        for label, ms in (("Slow", 140), ("Original-ish", 83), ("Fast", 55), ("Very Fast", 35)):
            self.speed_combo.addItem(label, ms)
        self.speed_combo.setCurrentText("Original-ish")
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        nav_row.addWidget(self.speed_combo)
        nav_row.addStretch()
        right_layout.addLayout(nav_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._image_label = QLabel("No frame")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._image_label)
        self._scroll.viewport().installEventFilter(self)
        right_layout.addWidget(self._scroll, stretch=1)

        self.thumb_list = QListWidget()
        self.thumb_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumb_list.setFlow(QListWidget.Flow.LeftToRight)
        self.thumb_list.setWrapping(False)
        self.thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumb_list.setIconSize(QSize(64, 40))
        self.thumb_list.setMaximumHeight(96)
        self.thumb_list.currentRowChanged.connect(self._on_thumb_selected)
        right_layout.addWidget(self.thumb_list)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self.save_frame_btn = QPushButton("Save Frame PNG...")
        self.save_frame_btn.clicked.connect(self._save_frame_png)
        action_row.addWidget(self.save_frame_btn)
        self.save_sheet_btn = QPushButton("Save Contact Sheet...")
        self.save_sheet_btn.clicked.connect(self._save_contact_sheet)
        action_row.addWidget(self.save_sheet_btn)
        self.export_frames_btn = QPushButton("Export Frames...")
        self.export_frames_btn.clicked.connect(self._export_frames)
        action_row.addWidget(self.export_frames_btn)
        right_layout.addLayout(action_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 760])
        self._set_controls_enabled(False)

    def set_dl_path(self, path: str):
        if path == self.dl_path:
            return
        self.dl_path = path
        self._reload()

    def focus_filter(self):
        self._filter.setFocus()
        self._filter.selectAll()

    def _reload(self):
        self._play_timer.stop()
        self.play_btn.setText("Play")
        self._files = []
        self._list.clear()
        self._clear_sequence("Set a valid Darklands folder first.")
        if not self.dl_path or not os.path.isdir(self.dl_path):
            return
        self._files = [
            name for name in sorted(os.listdir(self.dl_path))
            if os.path.isfile(os.path.join(self.dl_path, name)) and name.upper().endswith(".PAN")
        ]
        for name in self._files:
            self._list.addItem(QListWidgetItem(name))
        self._apply_filter()
        if self._list.count():
            self._list.setCurrentRow(0)
            self._autoload_first_on_show = True
            self.info_label.setText("Select a PAN file from the list.")
            self._image_label.setText("Select a PAN file from the list.")
            if self.isVisible():
                self._load_current_or_first()
        else:
            self._clear_sequence("No PAN files found in the current Darklands folder.")

    def showEvent(self, event):
        super().showEvent(event)
        if self._autoload_first_on_show and not self._frame_pixmaps:
            QTimer.singleShot(50, self._load_current_or_first)

    def _load_current_or_first(self):
        if not self._autoload_first_on_show or not self._list.count():
            return
        item = self._list.currentItem() or self._list.item(0)
        if item is None:
            return
        self._autoload_first_on_show = False
        self._on_file_clicked(item)

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

    def _on_file_clicked(self, item: QListWidgetItem):
        path = os.path.join(self.dl_path, item.text())
        self._load_pan_file(path)

    def _load_pan_file(self, path: str):
        try:
            self._autoload_first_on_show = False
            from darklands.format_pan import HEIGHT, WIDTH, PanSequence

            sequence = PanSequence.from_file(path)
            pixmaps = []
            for rgba in sequence.iter_rgba_frames():
                image = QImage(rgba, WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
                pixmaps.append(QPixmap.fromImage(image))

            self._sequence = sequence
            self._frame_pixmaps = pixmaps
            self._selected_file = path
            self._frame_idx = 0
            self._rebuild_thumbnails()
            count = max(1, len(self._frame_pixmaps))
            self.frame_spin.blockSignals(True)
            self.frame_spin.setMaximum(count)
            self.frame_spin.setValue(1)
            self.frame_spin.blockSignals(False)
            self._set_controls_enabled(bool(self._frame_pixmaps))
            meta = sequence.metadata
            self.info_label.setText(
                f"{os.path.basename(path)}\n"
                f"Frames: {meta.frame_count}  Size: {meta.compressed_size:,} compressed / {meta.logical_size:,} decoded bytes\n"
                f"Palette: embedded VGA DAC, 256 colors  Spans: {meta.span_count}"
            )
            self._apply_current_frame()
        except Exception:
            self._clear_sequence(f"Error:\n{traceback.format_exc()}")

    def _clear_sequence(self, message: str):
        self._autoload_first_on_show = False
        self._sequence = None
        self._frame_pixmaps = []
        self._frame_idx = 0
        self._selected_file = ""
        self.thumb_list.clear()
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText(message)
        self.info_label.setText(message)
        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool):
        self.prev_btn.setEnabled(enabled)
        self.play_btn.setEnabled(enabled)
        self.next_btn.setEnabled(enabled)
        self.frame_spin.setEnabled(enabled)
        self.zoom_combo.setEnabled(enabled)
        self.speed_combo.setEnabled(enabled)
        self.save_frame_btn.setEnabled(enabled)
        self.save_sheet_btn.setEnabled(enabled)
        self.export_frames_btn.setEnabled(enabled)
        if not enabled:
            self._play_timer.stop()
            self.play_btn.setText("Play")

    def _apply_current_frame(self):
        if not self._frame_pixmaps:
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("No frame")
            return
        pixmap = self._frame_pixmaps[self._frame_idx]
        if abs(self._zoom - 1.0) < 1e-9:
            scaled = pixmap
        else:
            scaled = pixmap.scaled(
                max(1, int(pixmap.width() * self._zoom)),
                max(1, int(pixmap.height() * self._zoom)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self._image_label.setPixmap(scaled)
        self._image_label.resize(scaled.size())
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(self._frame_idx + 1)
        self.frame_spin.blockSignals(False)
        self._select_thumb_for_frame(self._frame_idx)

    def _prev_frame(self):
        if self._frame_pixmaps:
            self._frame_idx = (self._frame_idx - 1) % len(self._frame_pixmaps)
            self._apply_current_frame()

    def _next_frame(self):
        if self._frame_pixmaps:
            self._frame_idx = (self._frame_idx + 1) % len(self._frame_pixmaps)
            self._apply_current_frame()

    def _on_frame_spin(self, value: int):
        if self._frame_pixmaps:
            self._frame_idx = max(0, min(value - 1, len(self._frame_pixmaps) - 1))
            self._apply_current_frame()

    def _on_zoom_changed(self):
        self._zoom = float(self.zoom_combo.currentData() or 1.0)
        self._apply_current_frame()

    def _on_speed_changed(self):
        self._play_timer.setInterval(int(self.speed_combo.currentData() or 83))

    def _toggle_playback(self):
        if not self._frame_pixmaps:
            return
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.play_btn.setText("Play")
        else:
            self._play_timer.start()
            self.play_btn.setText("Stop")

    def _rebuild_thumbnails(self):
        self._syncing_thumb = True
        self.thumb_list.clear()
        step = max(1, len(self._frame_pixmaps) // 80)
        for idx, pixmap in enumerate(self._frame_pixmaps):
            if idx % step != 0 and idx != len(self._frame_pixmaps) - 1:
                continue
            thumb = pixmap.scaled(
                64, 40,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            item = QListWidgetItem(QIcon(thumb), str(idx + 1))
            item.setData(Qt.ItemDataRole.UserRole, idx)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.thumb_list.addItem(item)
        self._syncing_thumb = False

    def _select_thumb_for_frame(self, frame_idx: int):
        best_row = -1
        best_distance = None
        for row in range(self.thumb_list.count()):
            item = self.thumb_list.item(row)
            idx = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(idx, int):
                continue
            distance = abs(idx - frame_idx)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_row = row
        self._syncing_thumb = True
        if best_row >= 0:
            self.thumb_list.setCurrentRow(best_row)
        self._syncing_thumb = False
        if self.thumb_list.currentItem() is not None:
            self.thumb_list.scrollToItem(self.thumb_list.currentItem())

    def _on_thumb_selected(self, row: int):
        if self._syncing_thumb or row < 0:
            return
        item = self.thumb_list.item(row)
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(idx, int) and 0 <= idx < len(self._frame_pixmaps):
            self._frame_idx = idx
            self._apply_current_frame()

    def eventFilter(self, obj, event):
        if (obj is self._scroll.viewport()
                and event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            index = self.zoom_combo.currentIndex()
            if event.angleDelta().y() > 0:
                index += 1
            else:
                index -= 1
            self.zoom_combo.setCurrentIndex(max(0, min(self.zoom_combo.count() - 1, index)))
            return True
        return super().eventFilter(obj, event)

    def _save_frame_png(self):
        if not self._frame_pixmaps or not self._selected_file:
            return
        suggested = f"{os.path.splitext(os.path.basename(self._selected_file))[0]}_frame{self._frame_idx + 1:03d}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save PAN Frame", suggested, "PNG Images (*.png);;All Files (*)")
        if path:
            self._frame_pixmaps[self._frame_idx].save(path)

    def _save_contact_sheet(self):
        if not self._frame_pixmaps or not self._selected_file:
            return
        sample_count = min(16, len(self._frame_pixmaps))
        indexes = sorted({round(i * (len(self._frame_pixmaps) - 1) / max(1, sample_count - 1)) for i in range(sample_count)})
        cell_w, cell_h = 160, 100
        cols = min(4, len(indexes))
        rows = (len(indexes) + cols - 1) // cols
        sheet = QPixmap(cell_w * cols, cell_h * rows)
        sheet.fill(Qt.GlobalColor.black)
        painter = QPainter(sheet)
        for pos, idx in enumerate(indexes):
            thumb = self._frame_pixmaps[idx].scaled(cell_w, cell_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            painter.drawPixmap((pos % cols) * cell_w, (pos // cols) * cell_h, thumb)
        painter.end()
        suggested = f"{os.path.splitext(os.path.basename(self._selected_file))[0]}_sheet.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save PAN Contact Sheet", suggested, "PNG Images (*.png);;All Files (*)")
        if path:
            sheet.save(path)

    def _export_frames(self):
        if not self._frame_pixmaps or not self._selected_file:
            return
        target_dir = QFileDialog.getExistingDirectory(self, "Export PAN Frames", self.dl_path or "")
        if not target_dir:
            return
        stem = os.path.splitext(os.path.basename(self._selected_file))[0]
        written = 0
        for idx, pixmap in enumerate(self._frame_pixmaps, start=1):
            if pixmap.save(os.path.join(target_dir, f"{stem}_frame{idx:03d}.png")):
                written += 1
        QMessageBox.information(self, "Export complete", f"Exported {written} frame PNG(s).")

    def open_archive_entry(self, cat_path: str, entry_name: str, data: bytes | None = None):
        if not entry_name.upper().endswith(".PAN"):
            return False
        if data is None:
            return False
        temp_name = f"{os.path.basename(cat_path)} / {entry_name}"
        try:
            from darklands.format_pan import HEIGHT, WIDTH, PanSequence
            sequence = PanSequence.from_bytes(data, temp_name)
            self._sequence = sequence
            self._frame_pixmaps = [
                QPixmap.fromImage(QImage(rgba, WIDTH, HEIGHT, QImage.Format.Format_ARGB32))
                for rgba in sequence.iter_rgba_frames()
            ]
            self._selected_file = temp_name
            self._frame_idx = 0
            self._rebuild_thumbnails()
            count = max(1, len(self._frame_pixmaps))
            self.frame_spin.blockSignals(True)
            self.frame_spin.setMaximum(count)
            self.frame_spin.setValue(1)
            self.frame_spin.blockSignals(False)
            self._set_controls_enabled(bool(self._frame_pixmaps))
            self.info_label.setText(f"{temp_name}\nFrames: {sequence.frame_count}")
            self._apply_current_frame()
            return True
        except Exception:
            self._clear_sequence(f"Error:\n{traceback.format_exc()}")
            return False


class ResearchFilesConverter(_ResearchFileViewer):
    def __init__(self, parent=None):
        super().__init__(
            "Research Files",
            ("LEVEL0.ENM",),
            "20_File_Formats/By_Type/World_Data/darkland.enm.md",
            "Small or unusual files that are related to known formats but do not yet fit the main editor workflows cleanly.",
            parent,
        )
