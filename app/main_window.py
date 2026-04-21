from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DESCRIPTION, APP_NAME, APP_SHORT_NAME, APP_TAGLINE, load_app_icon, load_logo_pixmap
from app.settings import AppSettings
from app.theme import THEME_MODES, apply_theme
import re


_TREE_STRUCTURE = [
    ("Save Games", [
        ("Save Game Editor",        "save_converter",  "SaveGameConverter"),
    ]),
    ("Data", [
        ("Enemies",                 "data_converters", "EnemiesConverter"),
        ("Locations",               "data_editors",    "LocationsConverter"),
        ("Items, Saints, Formulae & Alchemy","data_editors",    "ItemsConverter"),
        ("World Map",               "data_converters", "MapConverter"),
        ("Cities",                  "data_editors",    "CitiesConverter"),
    ]),
    ("Text", [
        ("Dialog Cards (MSG)",      "text_converters", "DialogsConverter"),
        ("Descriptions (DSC)",      "data_editors",    "DescriptionsConverter"),
    ]),
    ("Images", [
        ("PIC Images",              "image_converters","PicConverter"),
        ("IMC Sprites",             "image_converters","ImcConverter"),
    ]),
    ("Fonts", [
        ("Font Viewer (FNT/UTL)",   "font_converter",  "FontConverter"),
    ]),
    ("Archive", [
        ("CAT Extractor",           "archive_converter","CatConverter"),
    ]),
    ("Research", [
        ("DGT Audio",               "audio_converters",    "DgtAudioConverter"),
        ("IMG Banks (WIP)",         "research_converters", "ImgResearchConverter"),
        ("PAN Sequences (WIP)",     "research_converters", "PanResearchConverter"),
        ("Research Files",          "research_converters", "ResearchFilesConverter"),
        ("DRLE Decompressor",       "image_converters","DrleConverter"),
    ]),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1150, 760)
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        self._converter_widgets = []
        self._widget_by_title = {}
        self._tree_item_by_title = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        lbl = QLabel("DL Data Path:")
        lbl.setFixedWidth(90)
        path_row.addWidget(lbl)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(
            "Path to the Darklands DL/ data folder (e.g. C:\\Darklands\\DL)"
        )
        path_row.addWidget(self.path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(browse_btn)
        root.addLayout(path_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(190)
        self.tree.setMaximumWidth(270)
        self.tree.setIndentation(14)
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(14, 14))
        splitter.addWidget(self.tree)

        self.stack = QStackedWidget()
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([210, 900])

        welcome = self._build_welcome_widget()
        self.stack.addWidget(welcome)

        self._build_tree()
        self._build_menu()

        self.tree.itemSelectionChanged.connect(self._on_tree_select)
        self.path_edit.textChanged.connect(self._on_path_changed)

        settings = AppSettings()
        saved_path = settings.get_dl_path()
        if saved_path:
            self.path_edit.setText(saved_path)
        saved_geom = settings.get_window_geometry()
        if saved_geom:
            self.restoreGeometry(saved_geom)

        self.statusBar().showMessage("Ready")

    def _build_welcome_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(42, 34, 42, 34)
        layout.setSpacing(14)

        logo = QLabel()
        pixmap = load_logo_pixmap(max_width=560, max_height=240)
        if not pixmap.isNull():
            logo.setPixmap(pixmap)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo.setStyleSheet(
                "QLabel {"
                "padding: 18px;"
                "border: 1px solid rgba(193, 152, 66, 0.30);"
                "border-radius: 18px;"
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
                " stop:0 rgba(77, 61, 28, 0.22),"
                " stop:1 rgba(22, 18, 12, 0.10));"
                "}"
            )
            layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignHCenter)

        title = QLabel(APP_NAME)
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(APP_DESCRIPTION)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #bca36a; font-size: 13px;")
        layout.addWidget(subtitle)

        hint = QLabel(
            "Choose a tool from the sidebar, then point DARK at your Darklands folder "
            "to inspect, edit, validate, and research game resources."
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8d99a6; font-size: 13px;")
        layout.addWidget(hint)

        micro = QLabel(APP_SHORT_NAME + "  •  " + APP_TAGLINE)
        micro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        micro.setStyleSheet("color: #7f8c99; font-size: 11px; letter-spacing: 0.6px;")
        layout.addWidget(micro)

        layout.addStretch()
        return widget

    def _build_menu(self):
        view_menu = self.menuBar().addMenu("&View")
        coverage_action = view_menu.addAction("Format Coverage")
        coverage_action.triggered.connect(self._show_coverage_report)
        validation_action = view_menu.addAction("Validation Report")
        validation_action.triggered.connect(self._show_validation_report)
        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self._theme_actions = {}
        current_mode = AppSettings().get_theme_mode().lower()
        for mode in THEME_MODES:
            action = QAction(mode.capitalize(), self)
            action.setCheckable(True)
            action.setChecked(mode == current_mode)
            action.triggered.connect(lambda checked, m=mode: self._set_theme_mode(m))
            theme_group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[mode] = action

        help_menu = self.menuBar().addMenu("&Help")
        about_action = help_menu.addAction(f"About {APP_SHORT_NAME}")
        about_action.triggered.connect(self._show_about)

    def _build_tree(self):
        bold_font = QFont()
        bold_font.setBold(True)
        category_icon = self._make_category_icon()
        tool_icon = self._make_tool_icon()

        for category_name, items in _TREE_STRUCTURE:
            cat_item = QTreeWidgetItem([category_name])
            cat_item.setFont(0, bold_font)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            cat_item.setIcon(0, category_icon)
            self.tree.addTopLevelItem(cat_item)

            for item_name, module_name, class_name in items:
                import importlib

                mod = importlib.import_module(f"app.converters.{module_name}")
                cls = getattr(mod, class_name)

                widget = cls()
                self._converter_widgets.append(widget)
                self._widget_by_title[item_name] = widget
                stack_idx = self.stack.count()
                self.stack.addWidget(widget)

                child = QTreeWidgetItem([item_name])
                child.setData(0, Qt.ItemDataRole.UserRole, stack_idx)
                child.setIcon(0, tool_icon)
                cat_item.addChild(child)
                self._tree_item_by_title[item_name] = child

            cat_item.setExpanded(True)

        self._propagate_path(self.path_edit.text())

    def _make_category_icon(self) -> QIcon:
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#b38f4d"))
        painter.drawRoundedRect(1, 3, 12, 9, 2, 2)
        painter.setBrush(QColor("#d7b56f"))
        painter.drawRoundedRect(1, 2, 6, 4, 2, 2)
        painter.end()
        return QIcon(pix)

    def _make_tool_icon(self) -> QIcon:
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#5ea7d6"), 1))
        painter.setBrush(QColor("#365c73"))
        painter.drawEllipse(3, 3, 8, 8)
        painter.end()
        return QIcon(pix)

    def _on_tree_select(self):
        items = self.tree.selectedItems()
        if not items:
            return
        idx = items[0].data(0, Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.stack.setCurrentIndex(idx)

    def _browse_path(self):
        current = self.path_edit.text()
        path = QFileDialog.getExistingDirectory(self, "Select DL Data Folder", current)
        if path:
            self.path_edit.setText(path)

    def _on_path_changed(self, path: str):
        AppSettings().set_dl_path(path)
        self._propagate_path(path)

    def _propagate_path(self, path: str):
        for widget in self._converter_widgets:
            widget.set_dl_path(path)

    def _show_about(self):
        from app.converters.about_converter import AboutDialog

        dialog = AboutDialog(self)
        dialog.exec()

    def _show_validation_report(self):
        from app.converters.validation_dialog import ValidationDialog

        dialog = ValidationDialog(self.path_edit.text().strip(), self)
        dialog.exec()

    def _show_coverage_report(self):
        from app.converters.coverage_dialog import CoverageDialog

        dialog = CoverageDialog(self.path_edit.text().strip(), self)
        dialog.exec()

    def open_editor(self, title: str):
        item = self._tree_item_by_title.get(title)
        if item is None:
            return None
        self.tree.setCurrentItem(item)
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.stack.setCurrentIndex(idx)
        return self._widget_by_title.get(title)

    def open_archive_entry(self, editor_title: str, cat_path: str, entry_name: str, data: bytes | None = None) -> bool:
        widget = self.open_editor(editor_title)
        if widget is None:
            return False
        opener = getattr(widget, "open_catalog_entry", None)
        if callable(opener):
            try:
                return bool(opener(cat_path, entry_name, data))
            except TypeError:
                return bool(opener(cat_path, entry_name))
        opener = getattr(widget, "open_archive_entry", None)
        if callable(opener):
            return bool(opener(cat_path, entry_name, data))
        return False

    def navigate_to_validation_issue(self, issue) -> bool:
        message = issue.message
        scope = issue.scope
        if scope.startswith("CTY") or scope.startswith("LOC/CTY"):
            match = re.search(r"City #(\d+)", message)
            widget = self.open_editor("Cities")
            if widget is not None and match:
                selector = getattr(widget, "select_record", None)
                if callable(selector):
                    selector(int(match.group(1)))
            return widget is not None
        if scope.startswith("LOC"):
            match = re.search(r"location #(\d+)", message, re.IGNORECASE)
            widget = self.open_editor("Locations")
            if widget is not None and match:
                selector = getattr(widget, "select_record", None)
                if callable(selector):
                    selector(int(match.group(1)))
            return widget is not None
        if scope.startswith("DSC"):
            widget = self.open_editor("Descriptions (DSC)")
            return widget is not None
        if scope.startswith("ENM"):
            widget = self.open_editor("Enemies")
            if widget is None:
                return False
            match = re.search(r"Enemy type #(\d+)", message)
            if match and hasattr(widget, "select_type"):
                widget.select_type(int(match.group(1)))
                return True
            match = re.search(r"Encounter #(\d+)", message)
            if match and hasattr(widget, "select_encounter"):
                widget.select_encounter(int(match.group(1)))
                return True
            return True
        if scope.startswith("ALC"):
            widget = self.open_editor("Items, Saints, Formulae & Alchemy")
            if widget is None:
                return False
            match = re.search(r"Formula #(\d+)", message)
            if match and hasattr(widget, "select_alchemy"):
                widget.select_alchemy(int(match.group(1)))
                return True
            return True
        if scope.startswith("MSG"):
            widget = self.open_editor("Dialog Cards (MSG)")
            if widget is None:
                return False
            match = re.search(r"([$\w]+\.MSG)", message, re.IGNORECASE)
            if match:
                opener = getattr(widget, "open_message", None)
                if callable(opener):
                    return bool(opener(match.group(1)))
            return True
        return False

    def _set_theme_mode(self, mode: str):
        AppSettings().set_theme_mode(mode)
        resolved = apply_theme(QApplication.instance(), mode)
        self.statusBar().showMessage(f"Theme: {mode.capitalize()} ({resolved})", 3000)

    def closeEvent(self, event):
        AppSettings().set_dl_path(self.path_edit.text())
        AppSettings().set_window_geometry(self.saveGeometry())
        super().closeEvent(event)
