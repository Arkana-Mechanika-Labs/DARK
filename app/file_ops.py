import os
import shutil
from datetime import datetime


def backup_existing_file(path: str) -> str | None:
    if not path or not os.path.isfile(path):
        return None
    backup_path = path + ".bak"
    shutil.copy2(path, backup_path)
    return backup_path


def backup_label(path: str | None) -> str:
    if not path:
        return "no backup"
    return os.path.basename(path)
