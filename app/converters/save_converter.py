"""
Save Game Editor — browse, view, and edit Darklands .SAV files.
"""
import os
import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QSplitter, QListWidget, QListWidgetItem, QFrame,
    QScrollArea, QTabWidget, QSpinBox, QComboBox, QFormLayout,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QMessageBox, QTextBrowser,
)
from PySide6.QtGui import QFont, QPixmap, QPen, QPainter, QColor
from PySide6.QtCore import Qt


# ── label maps ────────────────────────────────────────────────────────────────

_ATTR_LABELS = {
    'end': 'Endurance',    'str': 'Strength',     'agl': 'Agility',
    'per': 'Perception',   'int': 'Intelligence',  'chr': 'Charisma',
    'df':  'Divine Favor',
}
_SKILL_LABELS = {
    'wEdg': 'Edge Weapons',   'wImp': 'Impact Weapons', 'wFll': 'Flail & Chain',
    'wPol': 'Polearms',       'wThr': 'Thrown',
    'wBow': 'Bow',            'wMsl': 'Crossbow',
    'alch': 'Alchemy',        'relg': 'Religion',       'virt': 'Virtue',
    'spkC': 'Speak Common',   'spkL': 'Speak Latin',    'r_w':  'Read/Write',
    'heal': 'Healing',        'artf': 'Artifice',
    'stlh': 'Stealth',        'strW': 'Streetwise',
    'ride': 'Riding',         'wdWs': 'Woodswise',
}

# Equipment slot label → field name in char['equip']
_EQUIP_DISPLAY = [
    ("Weapon",         'weapon_type',    'weapon_quality'),
    ("Body Armour",    'vital_type',     'vital_quality'),
    ("Leg Armour",     'leg_type',       'leg_quality'),
    ("Shield",         'shield_type',    'shield_quality'),
    ("Missile Weapon", 'missile_type',   'missile_quality'),
]


def _sep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _bold_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight: bold;")
    return lbl


# ── main widget ───────────────────────────────────────────────────────────────

class SaveGameConverter(QWidget):
    """Browse and edit Darklands save game files."""

    _auto_on_path = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path   = ""
        self._sav_path: str | None  = None
        self._header:   dict | None = None
        self._party:    dict | None = None
        self._events:   list | None = None
        self._locations: list | None = None
        self._raw:      bytes | None = None
        self._item_names: list[str]  = []   # indexed by item id-1
        self._world_locations: list[dict] = []
        self._quest_map_cache: QPixmap | None = None
        self._loading  = False
        self._dirty    = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # Title
        title = QLabel("Save Game Editor")
        f = title.font(); f.setPointSize(11); f.setBold(True); title.setFont(f)
        root.addWidget(title)
        root.addWidget(_sep())

        # ── File picker row ──────────────────────────────────────────────
        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        file_row.addWidget(QLabel("Save File:"))

        self._file_combo = QComboBox()
        self._file_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._file_combo.currentIndexChanged.connect(self._on_combo_changed)
        file_row.addWidget(self._file_combo)

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_file)
        file_row.addWidget(browse_btn)

        reload_btn = QPushButton("Reload")
        reload_btn.setFixedWidth(70)
        reload_btn.clicked.connect(self._reload)
        file_row.addWidget(reload_btn)

        root.addLayout(file_row)

        # ── Tabs ─────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)

        self._tabs.addTab(self._build_party_tab(),      "Party")
        self._tabs.addTab(self._build_characters_tab(), "Characters")
        self._tabs.addTab(self._build_events_tab(),     "Quests / Events")

        # ── Action bar ───────────────────────────────────────────────────
        root.addWidget(_sep())
        action_row = QHBoxLayout()
        self._status_lbl = QLabel("No file loaded.")
        self._status_lbl.setStyleSheet("color: #888; font-size: 8pt;")
        action_row.addWidget(self._status_lbl)
        action_row.addStretch()

        backup_btn = QPushButton("Save (with backup)")
        backup_btn.setFixedWidth(150)
        backup_btn.clicked.connect(self._save_with_backup)
        action_row.addWidget(backup_btn)

        save_as_btn = QPushButton("Save As…")
        save_as_btn.setFixedWidth(90)
        save_as_btn.clicked.connect(self._save_as)
        action_row.addWidget(save_as_btn)

        root.addLayout(action_row)

    # ── Tab builders ──────────────────────────────────────────────────────────

    def _build_party_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._pf = {}

        # Save info
        info_box = QGroupBox("Save Info")
        fl = QFormLayout(info_box)
        fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._pf['location'] = QLabel()
        fl.addRow("Location:", self._pf['location'])

        self._pf['location_id'] = QSpinBox()
        self._pf['location_id'].setRange(0, 65535)
        self._pf['location_id'].valueChanged.connect(lambda: self._mark_dirty())
        fl.addRow("Location Id:", self._pf['location_id'])

        self._pf['coord_x'] = QSpinBox()
        self._pf['coord_x'].setRange(0, 65535)
        self._pf['coord_x'].valueChanged.connect(lambda: self._mark_dirty())
        fl.addRow("Coord X:", self._pf['coord_x'])

        self._pf['coord_y'] = QSpinBox()
        self._pf['coord_y'].setRange(0, 65535)
        self._pf['coord_y'].valueChanged.connect(lambda: self._mark_dirty())
        fl.addRow("Coord Y:", self._pf['coord_y'])

        self._pf['curr_menu'] = QSpinBox()
        self._pf['curr_menu'].setRange(0, 65535)
        self._pf['curr_menu'].valueChanged.connect(lambda: self._mark_dirty())
        fl.addRow("Current Menu:", self._pf['curr_menu'])

        self._pf['prev_menu'] = QSpinBox()
        self._pf['prev_menu'].setRange(0, 65535)
        self._pf['prev_menu'].valueChanged.connect(lambda: self._mark_dirty())
        fl.addRow("Previous Menu:", self._pf['prev_menu'])

        self._pf['party_leader_index'] = QSpinBox()
        self._pf['party_leader_index'].setRange(0, 4)
        self._pf['party_leader_index'].valueChanged.connect(lambda: self._mark_dirty())
        fl.addRow("Party Leader:", self._pf['party_leader_index'])

        self._pf['party_order'] = QLineEdit()
        self._pf['party_order'].setPlaceholderText("e.g. 0,1,2,3,4")
        self._pf['party_order'].textEdited.connect(lambda: self._mark_dirty())
        fl.addRow("Walking Order:", self._pf['party_order'])

        self._pf['label'] = QLineEdit()
        self._pf['label'].setMaxLength(22)
        self._pf['label'].textEdited.connect(lambda: self._mark_dirty())
        fl.addRow("Save Label:", self._pf['label'])

        lay.addWidget(info_box)

        # Money
        money_box = QGroupBox("Party Money")
        ml = QFormLayout(money_box)
        ml.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for key, label in (('florins', 'Florins (gold)'),
                           ('groschen', 'Groschen (silver)'),
                           ('pfennigs', 'Pfennigs (copper)')):
            sb = QSpinBox()
            sb.setRange(0, 65535)
            sb.setFixedWidth(110)
            sb.valueChanged.connect(lambda: self._mark_dirty())
            ml.addRow(label + ":", sb)
            self._pf[key] = sb

        self._pf['bank_notes'] = QSpinBox()
        self._pf['bank_notes'].setRange(0, 65535)
        self._pf['bank_notes'].setFixedWidth(110)
        self._pf['bank_notes'].valueChanged.connect(lambda: self._mark_dirty())
        ml.addRow("Bank Notes:", self._pf['bank_notes'])

        lay.addWidget(money_box)

        # Party status
        status_box = QGroupBox("Party Status")
        sl = QFormLayout(status_box)
        sl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._pf['reputation'] = QSpinBox()
        self._pf['reputation'].setRange(-32768, 32767)
        self._pf['reputation'].setFixedWidth(110)
        self._pf['reputation'].valueChanged.connect(lambda: self._mark_dirty())
        sl.addRow("Reputation:", self._pf['reputation'])

        self._pf['philo_stone'] = QSpinBox()
        self._pf['philo_stone'].setRange(0, 65535)
        self._pf['philo_stone'].setFixedWidth(110)
        self._pf['philo_stone'].valueChanged.connect(lambda: self._mark_dirty())
        sl.addRow("Philosopher's Stone:", self._pf['philo_stone'])

        lay.addWidget(status_box)
        lay.addStretch()
        return scroll

    def _build_characters_tab(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._char_list = QListWidget()
        self._char_list.setMaximumWidth(200)
        self._char_list.setMinimumWidth(130)
        self._char_list.setFont(QFont("Courier New", 9))
        self._char_list.currentRowChanged.connect(self._on_char_selected)
        splitter.addWidget(self._char_list)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._char_form_widget = QWidget()
        scroll.setWidget(self._char_form_widget)
        self._char_form_lay = QVBoxLayout(self._char_form_widget)
        self._char_form_lay.setContentsMargins(12, 10, 12, 10)
        self._char_form_lay.setSpacing(12)
        self._char_form_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        splitter.addWidget(scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 720])
        return splitter

    def _build_events_tab(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        lay.addWidget(_bold_label("Quest / Event Records"))

        self._events_table = QTableWidget(0, 6)
        self._events_table.setHorizontalHeaderLabels(
            ["#", "Quest Giver", "Destination", "Source", "Required Item", "Summary"])
        self._events_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._events_table.setFont(QFont("Courier New", 9))
        self._events_table.itemSelectionChanged.connect(self._on_event_selection_changed)
        lay.addWidget(self._events_table)

        lay.addWidget(_bold_label("Visited Locations"))

        self._locs_table = QTableWidget(0, 3)
        self._locs_table.setHorizontalHeaderLabels(["#", "Name", "Local Reputation"])
        self._locs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._locs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._locs_table.setFont(QFont("Courier New", 9))
        lay.addWidget(self._locs_table)

        splitter.addWidget(w)

        detail = QWidget()
        dlay = QVBoxLayout(detail)
        dlay.setContentsMargins(10, 10, 10, 10)
        dlay.setSpacing(8)
        dlay.addWidget(_bold_label("Quest Location"))

        self._quest_info = QTextBrowser()
        self._quest_info.setOpenExternalLinks(False)
        self._quest_info.setMinimumHeight(140)
        dlay.addWidget(self._quest_info)

        self._quest_map = QLabel()
        self._quest_map.setMinimumSize(320, 220)
        self._quest_map.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._quest_map.setStyleSheet(
            "QLabel { background:#111; border:1px solid #333; border-radius:6px; }"
        )
        dlay.addWidget(self._quest_map, stretch=1)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([760, 340])
        return splitter

    # ── path / file management ────────────────────────────────────────────────

    def set_dl_path(self, path: str):
        self.dl_path = path
        if path:
            self._refresh_combo()
            self._try_load_item_names()

    def showEvent(self, event):
        super().showEvent(event)
        if self.dl_path and self._file_combo.count() <= 1:
            self._refresh_combo()

    def _refresh_combo(self):
        from darklands.reader_sav import find_save_files
        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        self._file_combo.addItem("(select a save file…)", None)
        for label, path in find_save_files(self.dl_path):
            self._file_combo.addItem(label, path)
        self._file_combo.blockSignals(False)

    def _on_combo_changed(self, idx):
        path = self._file_combo.itemData(idx)
        if path:
            self._load(path)

    def _browse_file(self):
        start = self.dl_path or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Save File", start,
            "Save Files (*.SAV *.sav);;All Files (*)"
        )
        if not path:
            return
        # Add to combo if not present
        for i in range(self._file_combo.count()):
            if self._file_combo.itemData(i) == path:
                self._file_combo.setCurrentIndex(i)
                return
        self._file_combo.addItem(os.path.basename(path), path)
        self._file_combo.setCurrentIndex(self._file_combo.count() - 1)

    def _reload(self):
        if self._sav_path:
            self._load(self._sav_path)

    def _try_load_item_names(self):
        try:
            from darklands.reader_lst import readData
            items, _, _ = readData(self.dl_path)
            self._item_names = [it.get('name', '') for it in items]
        except Exception:
            self._item_names = []
        try:
            from darklands.reader_loc import readData as read_loc
            self._world_locations = read_loc(self.dl_path)
        except Exception:
            self._world_locations = []
        self._quest_map_cache = None

    # ── load ──────────────────────────────────────────────────────────────────

    def _load(self, path: str):
        try:
            from darklands.reader_sav import read_file
            header, party, events, locations, raw = read_file(path)
        except Exception:
            QMessageBox.critical(self, "Load Error",
                                 f"Failed to load:\n{traceback.format_exc()}")
            return

        self._sav_path  = path
        self._header    = header
        self._party     = party
        self._events    = events
        self._locations = locations
        self._raw       = raw
        self._dirty     = False
        self._loading   = True
        try:
            self._populate_party_tab(header)
            self._populate_char_list(party)
            self._populate_events_tab(events, locations)
        finally:
            self._loading = False

        n = party['n_defined']
        self._status_lbl.setText(
            f"{os.path.basename(path)}  —  {n} character{'s' if n != 1 else ''}  —  saved"
        )

    # ── populate ──────────────────────────────────────────────────────────────

    def _populate_party_tab(self, h):
        pf = self._pf
        pf['location'].setText(h.get('location', ''))
        pf['label'].setText(h.get('label', ''))
        pf['location_id'].setValue(h.get('location_id', 0))
        coords = h.get('coords', (0, 0))
        pf['coord_x'].setValue(coords[0])
        pf['coord_y'].setValue(coords[1])
        pf['curr_menu'].setValue(h.get('curr_menu', 0))
        pf['prev_menu'].setValue(h.get('prev_menu', 0))
        pf['party_leader_index'].setValue(h.get('party_leader_index', 0))
        pf['party_order'].setText(', '.join(str(x) for x in h.get('party_order_indices', [])))
        pf['florins'].setValue(h.get('florins', 0))
        pf['groschen'].setValue(h.get('groschen', 0))
        pf['pfennigs'].setValue(h.get('pfennigs', 0))
        pf['bank_notes'].setValue(h.get('bank_notes', 0))
        pf['reputation'].setValue(h.get('reputation', 0))
        pf['philo_stone'].setValue(h.get('philo_stone', 0))

    def _populate_char_list(self, party):
        self._char_list.clear()
        active = set(party.get('party_ids', []))
        for i, char in enumerate(party['characters']):
            name = char.get('full_name') or f"Character {i + 1}"
            # gender: 0 = female, 1 = male
            gender_sym = 'M' if char.get('gender') else 'F'
            marker = '*' if i in active else ' '
            item = QListWidgetItem(f"{i + 1:2d}. {marker}[{gender_sym}] {name}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._char_list.addItem(item)
        if party['characters']:
            self._char_list.setCurrentRow(0)

    def _populate_events_tab(self, events, locations):
        self._events_table.setRowCount(len(events))
        for r, ev in enumerate(events):
            self._events_table.setItem(r, 0, QTableWidgetItem(str(r + 1)))
            self._events_table.setItem(r, 1, QTableWidgetItem(self._quest_giver_name(ev.get('quest_giver', 0))))
            self._events_table.setItem(r, 2, QTableWidgetItem(self._location_name(ev.get('dest_location_id', 0))))
            self._events_table.setItem(r, 3, QTableWidgetItem(self._location_name(ev.get('src_location_id', 0))))
            rid = ev.get('required_item_id', 0)
            self._events_table.setItem(r, 4,
                QTableWidgetItem(f"{rid} — {self._item_name(rid)}" if rid else ""))
            self._events_table.setItem(r, 5, QTableWidgetItem(self._event_summary(ev)))

        self._locs_table.setRowCount(len(locations))
        for r, loc in enumerate(locations):
            self._locs_table.setItem(r, 0, QTableWidgetItem(str(r + 1)))
            self._locs_table.setItem(r, 1, QTableWidgetItem(loc.get('name', '')))
            self._locs_table.setItem(r, 2, QTableWidgetItem(str(loc.get('local_reputation', 0))))
        if events:
            self._events_table.selectRow(0)
            self._show_event_detail(0)
        else:
            self._quest_info.setHtml("<p style='color:#888'>No active event records in this save.</p>")
            self._quest_map.clear()

    def _quest_giver_name(self, giver_id: int) -> str:
        return {
            0: "Merchant",
            4: "Foreign Trader",
            5: "Pharmacist",
            6: "Medici",
            7: "Hanseatic League",
            8: "Fugger",
            9: "Schulz",
            10: "Mayor",
        }.get(giver_id, str(giver_id))

    def _location_name(self, loc_id: int) -> str:
        if 0 <= loc_id < len(self._world_locations):
            loc = self._world_locations[loc_id]
            return f"{loc_id} — {loc.get('name', '(unnamed)')}"
        return str(loc_id)

    def _event_summary(self, ev: dict) -> str:
        dest_id = ev.get('dest_location_id', 0)
        src_id = ev.get('src_location_id', 0)
        rid = ev.get('required_item_id', 0)
        giver = self._quest_giver_name(ev.get('quest_giver', 0))
        if rid:
            return (
                f"Retrieve {self._item_name(rid)} near {self._location_name(dest_id)} "
                f"for {giver} in {self._location_name(src_id)}."
            )
        return (
            f"Deal with raubritter activity near {self._location_name(dest_id)} "
            f"and report to {giver} in {self._location_name(src_id)}."
        )

    def _on_event_selection_changed(self):
        rows = self._events_table.selectionModel().selectedRows()
        if not rows:
            return
        self._show_event_detail(rows[0].row())

    def _show_event_detail(self, row: int):
        if self._events is None or row < 0 or row >= len(self._events):
            return
        ev = self._events[row]
        dest_id = ev.get('dest_location_id', 0)
        src_id = ev.get('src_location_id', 0)
        rid = ev.get('required_item_id', 0)
        giver = self._quest_giver_name(ev.get('quest_giver', 0))
        self._quest_info.setHtml(
            "<h3 style='margin-bottom:4px'>Quest Detail</h3>"
            f"<p><b>Giver:</b> {giver}</p>"
            f"<p><b>Destination:</b> {self._location_name(dest_id)}</p>"
            f"<p><b>Source:</b> {self._location_name(src_id)}</p>"
            f"<p><b>Required Item:</b> {self._item_name(rid) if rid else 'None / raubritter task'}</p>"
            f"<p style='color:#d0b06a'>{self._event_summary(ev)}</p>"
        )
        self._render_quest_map(ev)

    def _render_quest_map(self, ev: dict):
        try:
            base = self._quest_map_base()
        except Exception:
            self._quest_map.setText("Map preview unavailable.")
            return
        pm = QPixmap(base)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(Qt.GlobalColor.black, 1))

        party_coords = None
        if self._header:
            loc_id = self._header.get('location_id', -1)
            if 0 <= loc_id < len(self._world_locations):
                party_coords = self._world_locations[loc_id].get('coords')
            elif isinstance(self._header.get('coords'), tuple):
                party_coords = self._header.get('coords')

        markers = [
            (self._coords_for_loc(ev.get('src_location_id', -1)), QColor(70, 150, 235), 5),
            (self._coords_for_loc(ev.get('dest_location_id', -1)), QColor(220, 170, 60), 6),
            (party_coords, QColor(80, 220, 180), 5),
        ]
        for coords, color, radius in markers:
            if not coords:
                continue
            x, y = self._map_point(coords, pm.width(), pm.height())
            painter.setBrush(color)
            painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)

        painter.end()
        self._quest_map.setPixmap(pm)

    def _coords_for_loc(self, loc_id: int):
        if 0 <= loc_id < len(self._world_locations):
            return self._world_locations[loc_id].get('coords')
        return None

    def _quest_map_base(self):
        if self._quest_map_cache is not None:
            return self._quest_map_cache
        from app.converters.map_graphics import _load_sprite_sheets, _render_map_pixmap
        from darklands.reader_map import readData as read_map

        map_data = read_map(self.dl_path)
        sheets = _load_sprite_sheets(self.dl_path, 1)
        raw = _render_map_pixmap(map_data, 1, sheets)
        self._quest_map_cache = raw.scaled(
            320,
            220,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return self._quest_map_cache

    def _map_point(self, coords, width: int, height: int):
        tx, ty = int(coords[0]), int(coords[1])
        px = tx * 16 + (8 if ty & 1 else 0) + 8
        py = ty * 4 + 8
        sx = int(px / (5240 or 1) * width)
        sy = int(py / (3732 or 1) * height)
        return sx, sy

    # ── character form ────────────────────────────────────────────────────────

    def _on_char_selected(self, row: int):
        if self._loading or row < 0 or self._party is None:
            return
        if row < len(self._party['characters']):
            self._build_char_form(row)

    def _build_char_form(self, char_idx: int):
        # Clear old form
        while self._char_form_lay.count():
            item = self._char_form_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        char = self._party['characters'][char_idx]
        self._cf: dict = {}

        # ── Identity ──────────────────────────────────────────────────────
        id_box = QGroupBox("Identity")
        fl = QFormLayout(id_box)
        fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        full = QLineEdit(char.get('full_name', ''))
        full.setMaxLength(24)
        full.textEdited.connect(lambda v, ci=char_idx: self._char_field('full_name', v, ci))
        fl.addRow("Full Name:", full)
        self._cf['full_name'] = full

        short = QLineEdit(char.get('short_name', ''))
        short.setMaxLength(10)
        short.textEdited.connect(lambda v, ci=char_idx: self._char_field('short_name', v, ci))
        fl.addRow("Short Name:", short)
        self._cf['short_name'] = short

        age_sb = QSpinBox()
        age_sb.setRange(1, 200)
        age_sb.setFixedWidth(80)
        age_sb.setValue(char.get('age', 20))
        age_sb.valueChanged.connect(lambda v, ci=char_idx: self._char_field('age', v, ci))
        fl.addRow("Age:", age_sb)
        self._cf['age'] = age_sb

        gender_cb = QComboBox()
        gender_cb.addItem("Female", 0)
        gender_cb.addItem("Male",   1)
        gender_cb.setCurrentIndex(1 if char.get('gender') else 0)
        gender_cb.setFixedWidth(110)
        gender_cb.currentIndexChanged.connect(
            lambda _, ci=char_idx: self._char_field(
                'gender', gender_cb.currentData(), ci))
        fl.addRow("Gender:", gender_cb)
        self._cf['gender'] = gender_cb

        self._char_form_lay.addWidget(id_box)

        # ── Attributes ────────────────────────────────────────────────────
        from darklands.reader_sav import ATTR_KEYS
        attr_box = QGroupBox("Attributes")
        attr_vlay = QVBoxLayout(attr_box)
        attr_vlay.setSpacing(4)

        hdr = QHBoxLayout()
        for txt, w in (("Attribute", 150), ("Current", 80), ("Max", 80)):
            l = QLabel(txt)
            l.setFixedWidth(w)
            if txt != "Attribute":
                l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet("font-weight: bold;")
            hdr.addWidget(l)
        hdr.addStretch()
        attr_vlay.addLayout(hdr)
        attr_vlay.addWidget(_sep())

        attrs_cur = char.get('attrs_cur', {})
        attrs_max = char.get('attrs_max', {})
        for k in ATTR_KEYS:
            row = QHBoxLayout()
            lbl = QLabel(_ATTR_LABELS.get(k, k))
            lbl.setFixedWidth(150)
            row.addWidget(lbl)

            cur_sb = QSpinBox()
            cur_sb.setRange(0, 255); cur_sb.setFixedWidth(70)
            cur_sb.setValue(attrs_cur.get(k, 0))
            cur_sb.valueChanged.connect(
                lambda v, key=k, ci=char_idx: self._char_attr('cur', key, v, ci))
            row.addWidget(cur_sb)
            row.addSpacing(10)

            max_sb = QSpinBox()
            max_sb.setRange(0, 255); max_sb.setFixedWidth(70)
            max_sb.setValue(attrs_max.get(k, 0))
            max_sb.valueChanged.connect(
                lambda v, key=k, ci=char_idx: self._char_attr('max', key, v, ci))
            row.addWidget(max_sb)
            row.addStretch()
            attr_vlay.addLayout(row)
            self._cf[f'attr_cur_{k}'] = cur_sb
            self._cf[f'attr_max_{k}'] = max_sb

        self._char_form_lay.addWidget(attr_box)

        # ── Skills ────────────────────────────────────────────────────────
        from darklands.reader_sav import SKILL_KEYS
        skill_box = QGroupBox("Skills")
        skill_vlay = QVBoxLayout(skill_box)
        skill_vlay.setSpacing(4)

        hdr2 = QHBoxLayout()
        for txt, w in (("Skill", 160), ("Value", 80)):
            l = QLabel(txt)
            l.setFixedWidth(w)
            if txt != "Skill":
                l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet("font-weight: bold;")
            hdr2.addWidget(l)
        hdr2.addStretch()
        skill_vlay.addLayout(hdr2)
        skill_vlay.addWidget(_sep())

        skills = char.get('skills', {})
        for k in SKILL_KEYS:
            row = QHBoxLayout()
            lbl = QLabel(_SKILL_LABELS.get(k, k))
            lbl.setFixedWidth(160)
            row.addWidget(lbl)
            sb = QSpinBox()
            sb.setRange(0, 255); sb.setFixedWidth(70)
            sb.setValue(skills.get(k, 0))
            sb.valueChanged.connect(
                lambda v, key=k, ci=char_idx: self._char_skill(key, v, ci))
            row.addWidget(sb)
            row.addStretch()
            skill_vlay.addLayout(row)
            self._cf[f'skill_{k}'] = sb

        self._char_form_lay.addWidget(skill_box)

        # ── Equipment ─────────────────────────────────────────────────────
        equip = char.get('equip', {})
        eq_box = QGroupBox("Equipped Items")
        eq_fl = QFormLayout(eq_box)
        eq_fl.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for slot_label, type_key, qual_key in _EQUIP_DISPLAY:
            tid = equip.get(type_key, 0)
            qid = equip.get(qual_key, 0)
            if tid:
                txt = f"Type {tid}  (quality {qid})"
                style = ""
            else:
                txt = "— empty —"
                style = "color: #888;"
            l = QLabel(txt)
            l.setStyleSheet(style)
            eq_fl.addRow(slot_label + ":", l)
        self._char_form_lay.addWidget(eq_box)

        # ── Saints & Formulae bitmasks (read-only summary) ────────────────
        saint_bits   = char.get('saint_bits',   b'\x00' * 20)
        formula_bits = char.get('formula_bits', b'\x00' * 22)
        n_saints   = sum(bin(b).count('1') for b in saint_bits)
        n_formulae = sum(bin(b).count('1') for b in formula_bits)

        know_box = QGroupBox("Knowledge")
        kf = QFormLayout(know_box)
        kf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        kf.addRow("Saints known:",   QLabel(str(n_saints)))
        kf.addRow("Formulae known:", QLabel(str(n_formulae)))
        self._char_form_lay.addWidget(know_box)

        # ── Inventory ─────────────────────────────────────────────────────
        active_items = [it for it in char.get('items', []) if it.get('id', 0)]
        inv_box = QGroupBox(f"Inventory  ({len(active_items)} items, "
                            f"{char.get('num_items', 0)} declared active)")
        inv_lay = QVBoxLayout(inv_box)

        inv_table = QTableWidget(len(active_items), 5)
        inv_table.setHorizontalHeaderLabels(["ID", "Name", "Qty", "Quality", "Weight"])
        inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        inv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        inv_table.setFont(QFont("Courier New", 8))
        inv_table.setMaximumHeight(220)
        for r, it in enumerate(active_items):
            iid = it.get('id', 0)
            inv_table.setItem(r, 0, QTableWidgetItem(str(iid)))
            inv_table.setItem(r, 1, QTableWidgetItem(self._item_name(iid)))
            inv_table.setItem(r, 2, QTableWidgetItem(str(it.get('quantity', 1))))
            inv_table.setItem(r, 3, QTableWidgetItem(str(it.get('quality', 0))))
            inv_table.setItem(r, 4, QTableWidgetItem(str(it.get('weight', 0))))
        inv_lay.addWidget(inv_table)
        self._char_form_lay.addWidget(inv_box)
        self._char_form_lay.addStretch()

    def _item_name(self, item_id: int) -> str:
        if item_id and 1 <= item_id <= len(self._item_names):
            return self._item_names[item_id - 1]
        return f"(#{item_id})" if item_id else ""

    # ── data mutation ─────────────────────────────────────────────────────────

    def _mark_dirty(self):
        if not self._loading:
            self._dirty = True
            if self._sav_path:
                self._status_lbl.setText(
                    f"{os.path.basename(self._sav_path)}  —  unsaved changes")

    def _char_field(self, field: str, value, char_idx: int):
        if self._loading or self._party is None:
            return
        self._party['characters'][char_idx][field] = value
        if field == 'full_name':
            item = self._char_list.item(char_idx)
            if item:
                gender = self._party['characters'][char_idx].get('gender', 0)
                sym = 'M' if gender else 'F'
                item.setText(f"{char_idx + 1}. [{sym}] {value}")
        self._mark_dirty()

    def _char_attr(self, which: str, key: str, value: int, char_idx: int):
        if self._loading or self._party is None:
            return
        self._party['characters'][char_idx][f'attrs_{which}'][key] = value
        self._mark_dirty()

    def _char_skill(self, key: str, value: int, char_idx: int):
        if self._loading or self._party is None:
            return
        self._party['characters'][char_idx]['skills'][key] = value
        self._mark_dirty()

    # ── collect & save ────────────────────────────────────────────────────────

    def _collect_header(self):
        pf = self._pf
        self._header['label']       = pf['label'].text()
        self._header['location_id'] = pf['location_id'].value()
        self._header['coords']      = (pf['coord_x'].value(), pf['coord_y'].value())
        self._header['curr_menu']   = pf['curr_menu'].value()
        self._header['prev_menu']   = pf['prev_menu'].value()
        self._header['party_leader_index'] = pf['party_leader_index'].value()
        try:
            order = [int(x.strip()) for x in pf['party_order'].text().split(',') if x.strip()]
        except ValueError:
            order = [0, 1, 2, 3, 4]
        self._header['party_order_indices'] = order[:5]
        self._header['florins']     = pf['florins'].value()
        self._header['groschen']    = pf['groschen'].value()
        self._header['pfennigs']    = pf['pfennigs'].value()
        self._header['bank_notes']  = pf['bank_notes'].value()
        self._header['reputation']  = pf['reputation'].value()
        self._header['philo_stone'] = pf['philo_stone'].value()

    def _save_with_backup(self):
        if not self._sav_path or self._raw is None:
            QMessageBox.warning(self, "No File", "No save file loaded.")
            return
        backup = self._sav_path + '.bak'
        try:
            with open(backup, 'wb') as f:
                f.write(self._raw)
        except Exception as e:
            QMessageBox.warning(self, "Backup Failed", f"Could not write backup:\n{e}")
            return
        self._do_save(self._sav_path)

    def _save_as(self):
        if self._raw is None:
            QMessageBox.warning(self, "No File", "No save file loaded.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", self._sav_path or "",
            "Save Files (*.SAV *.sav);;All Files (*)"
        )
        if path:
            self._do_save(path)

    def _do_save(self, path: str):
        try:
            self._collect_header()
            from darklands.reader_sav import write_file
            write_file(path, self._header, self._party, self._raw)
            with open(path, 'rb') as f:
                self._raw = f.read()
            self._dirty    = False
            self._sav_path = path
            self._status_lbl.setText(
                f"{os.path.basename(path)}  —  saved successfully")
        except Exception:
            QMessageBox.critical(self, "Save Error",
                                 f"Failed to save:\n{traceback.format_exc()}")
