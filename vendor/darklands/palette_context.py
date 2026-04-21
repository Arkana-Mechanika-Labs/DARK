import os

from .format_pic import Pic, default_pal


def load_combat_palette(dl_path: str):
    """Return the combat/base palette used before ENEMYPAL overlays.

    Tactical sprites do not appear to use the raw VGA default palette directly.
    CHARPALT.PIC provides a much closer base palette for shared indices such as
    5 and 123, and we layer any missing entries over the generic fallback.
    """
    palette = list(default_pal)
    if not dl_path:
        return palette
    pic_path = os.path.join(dl_path, "PICS", "CHARPALT.PIC")
    if not os.path.isfile(pic_path):
        return palette
    try:
        pic = Pic(pic_path)
    except Exception:
        return palette
    if not pic.pal:
        return palette
    for idx, color in enumerate(pic.pal):
        if color is not None:
            palette[idx] = color
    return palette
