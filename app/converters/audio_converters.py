import os
import tempfile
import wave

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.converters.kb_note_dialog import KbNoteDialog
from app.format_coverage import resolve_kb_doc

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect
except Exception:  # pragma: no cover - optional multimedia runtime
    QAudioOutput = None
    QMediaPlayer = None
    QSoundEffect = None


class DgtAudioConverter(QWidget):
    _auto_on_path = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""
        self._kb_doc = resolve_kb_doc("20_File_Formats/By_Type/Audio/dgt_files.md")
        self._current_path = None
        self._temp_wav = None
        self._player = None
        self._audio = None
        self._sound = None
        self._build_ui()
        self._init_player()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        title = QLabel("DGT Audio")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        summary = QLabel(
            ".DGT files are Darklands presentation audio streams: raw unsigned "
            "8-bit mono PCM, typically played at 8000 Hz."
        )
        summary.setWordWrap(True)
        root.addWidget(summary)

        row = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter DGT files...")
        self._filter.textChanged.connect(self._apply_filter)
        row.addWidget(self._filter, stretch=1)

        self._kb_btn = QPushButton("Show KB Note")
        self._kb_btn.setEnabled(bool(self._kb_doc))
        self._kb_btn.clicked.connect(self._show_kb_note)
        row.addWidget(self._kb_btn)
        root.addLayout(row)

        split = QHBoxLayout()
        split.setSpacing(10)
        root.addLayout(split, stretch=1)

        self._list = QListWidget()
        self._list.setMinimumWidth(220)
        self._list.currentRowChanged.connect(self._on_selected)
        split.addWidget(self._list, stretch=0)

        detail_wrap = QVBoxLayout()
        detail_wrap.setSpacing(8)
        split.addLayout(detail_wrap, stretch=1)

        self._meta = QLabel("Set a valid Darklands folder to browse .DGT files.")
        self._meta.setWordWrap(True)
        self._meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_wrap.addWidget(self._meta)

        self._wave = QLabel()
        self._wave.setMinimumHeight(180)
        self._wave.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wave.setStyleSheet(
            "QLabel { background:#111; border:1px solid #333; border-radius:6px; }"
        )
        detail_wrap.addWidget(self._wave, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        detail_wrap.addLayout(actions)

        self._play_btn = QPushButton("Play")
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._toggle_playback)
        actions.addWidget(self._play_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_playback)
        actions.addWidget(self._stop_btn)

        export_btn = QPushButton("Export WAV...")
        export_btn.clicked.connect(self._export_wav)
        actions.addWidget(export_btn)

        open_btn = QPushButton("Open File...")
        open_btn.clicked.connect(self._browse_file)
        actions.addWidget(open_btn)

        actions.addStretch()

        self._status = QLabel("")
        self._status.setStyleSheet("color:#888; font-size:10px;")
        root.addWidget(self._status)

    def _init_player(self):
        if QSoundEffect is not None:
            self._sound = QSoundEffect(self)
            self._sound.setLoopCount(1)
            self._sound.setVolume(0.7)
            self._sound.playingChanged.connect(self._sync_buttons)
        if QMediaPlayer is None or QAudioOutput is None:
            if self._sound is not None:
                self._status.setText("Playback ready.")
                return
            self._status.setText("Playback unavailable: Qt multimedia runtime not found.")
            return
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.7)
        self._player.setAudioOutput(self._audio)
        self._player.playbackStateChanged.connect(self._sync_buttons)
        self._player.errorOccurred.connect(self._on_player_error)
        if self._sound is None:
            self._status.setText("Playback ready.")

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
        self._current_path = None
        self._meta.setText("Set a valid Darklands folder to browse .DGT files.")
        self._wave.clear()
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        if not self.dl_path or not os.path.isdir(self.dl_path):
            return
        matches = []
        try:
            for name in sorted(os.listdir(self.dl_path)):
                if name.upper().endswith(".DGT") and os.path.isfile(os.path.join(self.dl_path, name)):
                    matches.append(name)
        except OSError as exc:
            self._status.setText(str(exc))
            return
        for name in matches:
            self._list.addItem(QListWidgetItem(name))
        self._apply_filter()
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._meta.setText("No .DGT files found in the current Darklands folder.")

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

    def _browse_file(self):
        start = self.dl_path or ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open DGT File",
            start,
            "Darklands Audio (*.dgt *.DGT);;All Files (*)",
        )
        if not path:
            return
        self._load_path(path)

    def _on_selected(self, row: int):
        if row < 0 or row >= self._list.count():
            return
        item = self._list.item(row)
        if item.isHidden():
            return
        self._load_path(os.path.join(self.dl_path, item.text()))

    def _load_path(self, path: str):
        self._stop_playback()
        self._current_path = path
        try:
            data = open(path, "rb").read()
        except OSError as exc:
            self._meta.setText(f"Failed to read {path}\n\n{exc}")
            self._wave.clear()
            return

        sample_count = len(data)
        duration = sample_count / 8000.0 if sample_count else 0.0
        peak = max((abs(b - 128) for b in data), default=0)
        self._meta.setText(
            "\n".join(
                [
                    f"File: {os.path.basename(path)}",
                    f"Path: {path}",
                    f"Samples: {sample_count:,}",
                    f"Playback: unsigned 8-bit PCM, mono, 8000 Hz",
                    f"Duration: {duration:.2f} s",
                    f"Peak offset from silence: {peak}",
                ]
            )
        )
        self._wave.setPixmap(self._render_waveform(data))
        self._status.setText(f"Loaded {os.path.basename(path)}")
        self._prepare_temp_wav(data)
        self._sync_buttons()

    def _render_waveform(self, data: bytes) -> QPixmap:
        width, height = 720, 180
        pm = QPixmap(width, height)
        pm.fill(QColor("#111"))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#3b3b3b"), 1))
        mid = height // 2
        painter.drawLine(0, mid, width, mid)
        if data:
            step = max(1, len(data) // width)
            pen = QPen(QColor("#c39a42"), 1)
            painter.setPen(pen)
            for x in range(width):
                start = x * step
                chunk = data[start:start + step]
                if not chunk:
                    break
                hi = max(chunk)
                lo = min(chunk)
                y1 = int(((255 - hi) / 255.0) * (height - 12)) + 6
                y2 = int(((255 - lo) / 255.0) * (height - 12)) + 6
                painter.drawLine(x, y1, x, y2)
        painter.end()
        return pm

    def _prepare_temp_wav(self, data: bytes):
        self._cleanup_temp_wav()
        fd, path = tempfile.mkstemp(prefix="dark_dgt_", suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(1)
            wav_file.setframerate(8000)
            wav_file.writeframes(data)
        self._temp_wav = path
        if self._sound is not None:
            self._sound.setSource(QUrl.fromLocalFile(path))
        if self._player is not None:
            self._player.setSource(QUrl.fromLocalFile(path))

    def _toggle_playback(self):
        if not self._temp_wav:
            QMessageBox.information(
                self,
                "Playback unavailable",
                "Qt multimedia support is not available in this build.",
            )
            return
        if self._sound is not None:
            if self._sound.isPlaying():
                self._sound.stop()
            else:
                self._sound.play()
                self._status.setText("Playing via Qt sound effect.")
        elif self._player is not None:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
                self._status.setText("Playing via Qt media player.")
        else:
            QMessageBox.information(
                self,
                "Playback unavailable",
                "Qt multimedia support is not available in this build.",
            )
        self._sync_buttons()

    def _stop_playback(self):
        if self._sound is not None:
            self._sound.stop()
        if self._player is not None:
            self._player.stop()
        self._sync_buttons()

    def _sync_buttons(self, *_args):
        playable = bool(self._temp_wav) and (self._sound is not None or self._player is not None)
        self._play_btn.setEnabled(playable)
        sound_playing = self._sound.isPlaying() if self._sound is not None else False
        player_playing = (
            self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            if self._player is not None and QMediaPlayer is not None
            else False
        )
        if sound_playing or player_playing:
            self._play_btn.setText("Pause" if self._sound is None else "Replay")
            self._stop_btn.setEnabled(True)
        else:
            self._play_btn.setText("Play")
            self._stop_btn.setEnabled(playable)

    def _on_player_error(self, _error, message):
        if message:
            self._status.setText(message)

    def _export_wav(self):
        if not self._current_path:
            return
        default_name = os.path.splitext(os.path.basename(self._current_path))[0] + ".wav"
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export WAV",
            os.path.join(os.path.dirname(self._current_path), default_name),
            "WAV Audio (*.wav)",
        )
        if not out_path:
            return
        try:
            data = open(self._current_path, "rb").read()
            with wave.open(out_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(1)
                wav_file.setframerate(8000)
                wav_file.writeframes(data)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._status.setText(f"Exported WAV to {out_path}")

    def _show_kb_note(self):
        if not self._kb_doc:
            return
        dialog = KbNoteDialog(self._kb_doc, self)
        dialog.exec()

    def _cleanup_temp_wav(self):
        if self._temp_wav and os.path.exists(self._temp_wav):
            try:
                os.remove(self._temp_wav)
            except OSError:
                pass
        self._temp_wav = None

    def closeEvent(self, event):
        self._stop_playback()
        self._cleanup_temp_wav()
        super().closeEvent(event)
