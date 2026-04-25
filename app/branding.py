from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QIcon, QPixmap


APP_NAME = "DARK: Darklands Authoring & Resource Kit"
APP_SHORT_NAME = "DARK"
APP_TAGLINE = "Darklands Authoring & Resource Kit"
APP_VERSION = "0.9b3"
APP_YEAR = "2026"
APP_AUTHOR = "Arkana Mechanika Labs"
APP_DESCRIPTION = (
    "A Darklands editing workbench for practical inspection, authoring, validation, "
    "and resource exploration."
)


def asset_path(*parts: str) -> str:
    return str(Path(__file__).resolve().parent / "assets" / Path(*parts))


def logo_path() -> str:
    return asset_path("dark_logo.png")


def load_logo_pixmap(max_width: int | None = None, max_height: int | None = None) -> QPixmap:
    pixmap = QPixmap(logo_path())
    if pixmap.isNull():
        return pixmap
    if max_width or max_height:
        width = max_width or pixmap.width()
        height = max_height or pixmap.height()
        return pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pixmap


def load_app_icon() -> QIcon:
    pixmap = QPixmap(logo_path())
    if pixmap.isNull():
        return QIcon()
    side = min(pixmap.width(), pixmap.height())
    left = max(0, int(pixmap.width() * 0.18))
    top = max(0, int((pixmap.height() - side) * 0.5))
    side = min(side, pixmap.width() - left, pixmap.height() - top)
    crop = pixmap.copy(QRect(left, top, side, side))
    return QIcon(crop)
