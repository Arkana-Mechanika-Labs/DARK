"""
DARK: Darklands Authoring & Resource Kit
Entry point - sets up sys.path then launches the Qt app.
"""
import os
import sys


_here = os.path.dirname(os.path.abspath(__file__))

if not getattr(sys, "frozen", False):
    vendor_path = os.path.join(_here, "vendor")
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)


from PySide6.QtWidgets import QApplication


def main():
    from app.branding import APP_NAME, load_app_icon
    from app.settings import AppSettings
    from app.theme import apply_theme
    from app.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ArkanaM")
    app.setStyle("Fusion")
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    apply_theme(app, AppSettings().get_theme_mode())

    win = MainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
