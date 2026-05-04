from PySide6.QtCore import QSettings


class AppSettings:
    _ORG = "ArkanaM"
    _APP = "DARK"
    _LEGACY_APP = "DarklandsBrowser"

    def __init__(self):
        self._s = QSettings(self._ORG, self._APP)
        self._legacy = QSettings(self._ORG, self._LEGACY_APP)

    def _value(self, key: str, default=None):
        value = self._s.value(key, None)
        if value is not None:
            return value
        legacy = self._legacy.value(key, None)
        return default if legacy is None else legacy

    def get_dl_path(self) -> str:
        return self._value("dl_path", "")

    def set_dl_path(self, path: str):
        self._s.setValue("dl_path", path)

    def get_window_geometry(self):
        return self._value("window_geometry")

    def set_window_geometry(self, geometry):
        self._s.setValue("window_geometry", geometry)

    def get_theme_mode(self) -> str:
        return self._value("theme_mode", "system")

    def set_theme_mode(self, mode: str):
        self._s.setValue("theme_mode", mode)

    def get_mt32_roms_path(self) -> str:
        return self._value("mt32_roms_path", "")

    def set_mt32_roms_path(self, path: str):
        self._s.setValue("mt32_roms_path", path)
