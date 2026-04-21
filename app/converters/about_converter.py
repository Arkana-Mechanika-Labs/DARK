from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from app.branding import (
    APP_AUTHOR,
    APP_DESCRIPTION,
    APP_NAME,
    APP_SHORT_NAME,
    APP_VERSION,
    APP_YEAR,
    load_app_icon,
    load_logo_pixmap,
)


def _sep():
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.HLine)
    frame.setFrameShadow(QFrame.Shadow.Sunken)
    return frame


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_SHORT_NAME}")
        self.resize(680, 560)
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        logo = QLabel()
        pixmap = load_logo_pixmap(max_width=520, max_height=220)
        if not pixmap.isNull():
            logo.setPixmap(pixmap)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo.setStyleSheet(
                "QLabel {"
                "padding: 14px;"
                "border: 1px solid rgba(193, 152, 66, 0.28);"
                "border-radius: 16px;"
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
                " stop:0 rgba(79, 60, 20, 0.22),"
                " stop:1 rgba(20, 16, 9, 0.10));"
                "}"
            )
            root.addWidget(logo)

        title = QLabel(APP_NAME)
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel(APP_DESCRIPTION)
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #bca36a;")
        root.addWidget(subtitle)
        root.addWidget(_sep())

        overview = QLabel(
            "Current scope includes structured world-data editors, save editing, dialog cards, "
            "PIC and IMC tooling, palette-aware previews, CAT archive workflows, validation "
            "reports, and research placeholders for still-emerging formats."
        )
        overview.setWordWrap(True)
        root.addWidget(overview)

        project_info = QLabel(
            f"Author: {APP_AUTHOR}\n"
            f"Application: {APP_NAME}\n"
            f"Version: {APP_VERSION}\n"
            f"Year: {APP_YEAR}"
        )
        project_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        project_info.setStyleSheet("color: #97a7b9;")
        root.addWidget(project_info)

        credits_title = QLabel("Credits")
        credits_title.setObjectName("sectionTitle")
        root.addWidget(credits_title)

        credits = QPlainTextEdit()
        credits.setReadOnly(True)
        credits.setPlainText(
            "Credits\n"
            "\n"
            "Merle\n"
            "Joel \"Quadko\" McIntyre\n"
            "The whole Darklands Yahoo Group\n"
            "\n"
            "Dedicated to the memory of Arnold Hendrick."
        )
        root.addWidget(credits, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        root.addWidget(buttons)
