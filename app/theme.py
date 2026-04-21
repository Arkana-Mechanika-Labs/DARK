from PySide6.QtCore import Qt


THEME_MODES = ("system", "dark", "light")


_BASE_SHARED = """
QScrollArea {
    border: none;
    background: transparent;
}
QTabWidget::pane {
    border: 1px solid %(pane_border)s;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: %(tab_bg)s;
    border: 1px solid %(tab_border)s;
    padding: 6px 12px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: %(tab_selected)s;
}
QHeaderView::section {
    background: %(header_bg)s;
    border: 0;
    border-right: 1px solid %(header_border)s;
    border-bottom: 1px solid %(header_border)s;
    padding: 5px 6px;
    font-weight: 600;
}
QTreeWidget {
    background: %(tree_bg)s;
    border: 1px solid %(tree_border)s;
    border-radius: 8px;
    padding: 6px;
}
QTreeWidget::branch {
    background: transparent;
    border: none;
    image: none;
}
QTreeWidget::item {
    padding: 6px 8px;
    border-radius: 6px;
}
QTreeWidget::item:selected {
    background: %(tree_selected)s;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QTableWidget, QListWidget, QTreeWidget {
    border: 1px solid %(input_border)s;
    border-radius: 6px;
    background: %(input_bg)s;
    selection-background-color: %(selection_bg)s;
}
QGroupBox {
    border: 1px solid %(group_border)s;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 10px;
    background: %(group_bg)s;
}
QGroupBox::title {
    left: 12px;
    padding: 0 4px;
    color: %(group_title)s;
}
QPushButton {
    border: 1px solid %(button_border)s;
    border-radius: 6px;
    padding: 5px 12px;
    background: %(button_bg)s;
}
QPushButton:hover {
    background: %(button_hover)s;
}
QLabel#pageTitle {
    font-size: 16px;
    font-weight: 700;
}
QLabel#sectionTitle {
    font-size: 12px;
    font-weight: 700;
    color: %(section_title)s;
}
"""


_DARK = {
    "widget_bg": "#10151a",
    "widget_fg": "#dde6ef",
    "status_bg": "#0d1116",
    "status_fg": "#98a7b8",
    "pane_border": "#2f3843",
    "tab_bg": "#1a232b",
    "tab_border": "#33404c",
    "tab_selected": "#263542",
    "header_bg": "#1b2530",
    "header_border": "#2f3843",
    "tree_bg": "#171c22",
    "tree_border": "#2b3642",
    "tree_selected": "#304459",
    "input_border": "#34414e",
    "input_bg": "#171b21",
    "selection_bg": "#3b5873",
    "group_border": "#2d3742",
    "group_bg": "#11161b",
    "group_title": "#d7e4f1",
    "button_border": "#3c4a58",
    "button_bg": "#24303a",
    "button_hover": "#2b3946",
    "section_title": "#d7e4f1",
}

_LIGHT = {
    "widget_bg": "#eef3f7",
    "widget_fg": "#1e2a35",
    "status_bg": "#dde6ee",
    "status_fg": "#5b6b7c",
    "pane_border": "#b7c4d0",
    "tab_bg": "#dde6ee",
    "tab_border": "#b8c5d1",
    "tab_selected": "#f6fafc",
    "header_bg": "#dfe8ef",
    "header_border": "#bdc9d4",
    "tree_bg": "#f7fafc",
    "tree_border": "#c1ccd6",
    "tree_selected": "#cfe0ee",
    "input_border": "#bcc8d3",
    "input_bg": "#ffffff",
    "selection_bg": "#b9d1e5",
    "group_border": "#c2ccd5",
    "group_bg": "#f8fbfd",
    "group_title": "#233548",
    "button_border": "#b5c1cb",
    "button_bg": "#edf3f7",
    "button_hover": "#e0e9f0",
    "section_title": "#233548",
}


def _system_prefers_dark(app) -> bool:
    hints = getattr(app, "styleHints", None)
    if not callable(hints):
        return False
    style_hints = app.styleHints()
    color_scheme = getattr(style_hints, "colorScheme", None)
    if callable(color_scheme):
        try:
            return color_scheme() == Qt.ColorScheme.Dark
        except Exception:
            return False
    return False


def resolve_theme_mode(app, mode: str) -> str:
    mode = (mode or "system").lower()
    if mode not in THEME_MODES:
        mode = "system"
    if mode == "system":
        return "dark" if _system_prefers_dark(app) else "light"
    return mode


def theme_stylesheet(app, mode: str) -> str:
    palette = _DARK if resolve_theme_mode(app, mode) == "dark" else _LIGHT
    base = """
    QWidget {
        background: %(widget_bg)s;
        color: %(widget_fg)s;
    }
    QMainWindow::separator {
        background: %(pane_border)s;
        width: 1px;
        height: 1px;
    }
    QStatusBar {
        background: %(status_bg)s;
        color: %(status_fg)s;
    }
    """ % palette
    return base + (_BASE_SHARED % palette)


def apply_theme(app, mode: str) -> str:
    resolved = resolve_theme_mode(app, mode)
    app.setStyleSheet(theme_stylesheet(app, mode))
    app.setProperty("_theme_mode", mode)
    app.setProperty("_theme_resolved", resolved)
    return resolved
