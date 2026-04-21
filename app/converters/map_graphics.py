"""
Darklands world-map viewer / editor.

Tile geometry (from original Darklands engine):
    TW   = 16   tile width  (pixels at scale 1)
    TH   =  8   tile diamond height  (= tile_height in PureBasic source)
    TR   = 12   tile real height     (= tile_real_height; sprite height)
    VSTEP=  4   vertical row step    (= TH // 2)
    stagger = (TW // 2) * (ty & 1)  — odd rows shifted right 8 px

Pixel position of tile (tx, ty) at scale s:
    px = (tx * TW + (ty & 1) * (TW // 2)) * s
    py = ty * VSTEP * s

Tile sprite (TW*s × TR*s) is drawn at (px, py).
Rows overlap by (TR-VSTEP)*s = 8*s px, so render top→bottom.

Sprite sheet layout (MAPICONS.PIC / MAPICON2.PIC — 320×200):
    x = col_value * TW   (col_value = 4-bit adjacency bitmask, 0–15)
    y = tile_row  * TR   (tile_row  = terrain type, 0–15)
    Palette index 0 = transparent.

MapEditorWidget
  ├── toolbar  (scale, overlay toggles, view/edit mode, save)
  ├── QSplitter
  │     ├── _MapView (_MapScene)        — scrollable/zoomable map
  │     └── _InfoPalettePanel           — location info OR tile palette
  └── status bar
"""
import os
import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QSplitter, QGraphicsScene, QGraphicsView, QGraphicsEllipseItem,
    QGraphicsPixmapItem, QGraphicsItem, QGraphicsSimpleTextItem,
    QTextBrowser, QScrollArea,
    QGridLayout, QStackedWidget, QToolButton, QFrame, QSizePolicy,
    QFileDialog, QApplication,
)
from PySide6.QtGui import (
    QBrush, QColor, QPen, QPainter, QPixmap, QPolygon, QFont, QCursor, QImage,
    QIcon, QKeySequence, QShortcut,
)
from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QRect, QPoint, QPointF, QSize


# ── Tile geometry constants ──────────────────────────────────────────────────
TW    = 16   # tile width
TH    =  8   # tile diamond face height (= tile_height in PureBasic)
TR    = 12   # tile real height / sprite height (= tile_real_height)
VSTEP =  4   # vertical row step (= TH // 2)


# Background colour rendered under transparent tile pixels (plains/terrain green)
_MAP_BG_COLOR = (34, 100, 34)

# ── Tile colour / name tables (fallback when no sprites) ─────────────────────

_TILE_COLORS = [
    # Palette 0  (reader_map.py ASCII key: ' ....sppffttTTTT')
    # Colors measured from MAPICONS.PIC col=0 sprite averages.
    (  0,   0,   0),  #  0  ' '  Empty / transparent
    ( 38,  81, 171),  #  1  '.'  Deep Ocean
    ( 40,  82, 166),  #  2  '.'  Ocean
    ( 27,  77, 155),  #  3  '.'  Ocean
    ( 27,  86, 123),  #  4  '.'  Shallow Water
    (  6, 106,  89),  #  5  's'  Shore
    ( 22, 156,  93),  #  6  'p'  Plains
    (  4, 122,   0),  #  7  'p'  Plains
    (101, 117,  57),  #  8  'f'  Forest
    (143, 134,  14),  #  9  'f'  Forest
    ( 14, 119,   3),  # 10  't'  Light Forest
    ( 16, 129,   4),  # 11  't'  Light Forest
    ( 18, 119,   8),  # 12  'T'  Dense Forest
    ( 18, 113,   5),  # 13  'T'  Dense Forest
    ( 20, 112,   7),  # 14  'T'  Dense Forest
    ( 14, 114,  24),  # 15  'T'  Dense Forest
    # Palette 1  (reader_map.py ASCII key: 'HHhhMMAA/~~%Cc++')
    # Colors measured from MAPICON2.PIC col=0 sprite averages.
    ( 44,  84,  33),  # 16  'H'  Highlands
    ( 39,  78,  40),  # 17  'H'  Highlands
    ( 91,  65,  38),  # 18  'h'  Hills
    ( 91,  65,  38),  # 19  'h'  Hills
    (114, 127, 100),  # 20  'M'  Mountains
    (113, 127, 101),  # 21  'M'  Mountains
    (139, 146, 132),  # 22  'A'  Alpine
    (139, 147, 135),  # 23  'A'  Alpine
    (125, 135,  78),  # 24  '/'  Alpine Pass
    ( 42,  90, 148),  # 25  '~'  River/Coast
    ( 35,  95, 154),  # 26  '~'  River/Coast
    ( 57,  73, 102),  # 27  '%'  Special
    (132, 116, 103),  # 28  'C'  Cliffs
    (142, 117,  93),  # 29  'c'  Cliffs
    (101, 101, 198),  # 30  '+'  Unknown
    (198, 101, 101),  # 31  '+'  Unknown
]

# Names from Initialise_TilePanel() in the original PureBasic mapper source (mapper.pb)
_TILE_NAMES = [
    # Pal 0 — MAPICONS
    "Plain",           #  0
    "Ocean",           #  1
    "Major River",     #  2
    "Minor River",     #  3
    "Tidal Marsh",     #  4
    "Marsh",           #  5
    "Geest 0",         #  6
    "Geest 1",         #  7
    "Farm 0",          #  8
    "Farm 1",          #  9
    "Farm / Wood 0",   # 10
    "Farm / Wood 1",   # 11
    "Light Wood 1",    # 12
    "Light Wood 2",    # 13
    "Forest 0",        # 14
    "Forest 1",        # 15
    # Pal 1 — MAPICON2
    "Forest 2",        # 16
    "Forest 3",        # 17
    "Rock 0",          # 18
    "Rock 1",          # 19
    "Rock 2",          # 20
    "Rock 3",          # 21
    "Alps 4",          # 22
    "Alps 5",          # 23
    "Road",            # 24
    "Ford",            # 25
    "Ford 2",          # 26
    "Bridge",          # 27
    "row 12",          # 28  (not named in original source)
    "row 13",          # 29  (not named in original source)
    "row 14",          # 30  (not named in original source)
    "row 15",          # 31  (not named in original source)
]

_LOC_COLORS: dict[int, QColor] = {
    0:  QColor(220,  50,  50),
    1:  QColor(180,  30,  30),
    2:  QColor(160,  20,  20),
    3:  QColor(220, 190,  50),
    4:  QColor(150,  50, 180),
    5:  QColor(120, 120, 120),
    6:  QColor( 90,  90,  90),
    7:  QColor(150, 200,  80),
    8:  QColor(150, 200,  80),
    9:  QColor(180, 140,  80),
    10: QColor(160, 200,  80),
    13: QColor(130, 100,  70),
    15: QColor(255,  80,   0),
    16: QColor(100, 180, 220),
    17: QColor( 80, 160, 200),
    18: QColor(200, 200, 200),
    20: QColor(120,  50, 150),
    21: QColor(100,  40, 130),
    22: QColor(200,  60,  60),
    23: QColor(255,   0,   0),
    24: QColor(140, 120, 100),
    25: QColor(100, 180, 180),
    26: QColor(160, 120,  80),
}
_LOC_COLOR_DEFAULT = QColor(160, 160, 160)

# Maps loc["icon"] → (sheet_row, sheet_col) within MAPICON2.PIC.
# Exact mapping from PureBasic DisplayLocations (map.pbi).
# Icon 0 = city — text only, no sprite; intentionally absent from table.
# Row 12 = sprite row index 12 (y=144px); row 13 = village row (y=156px).
_LOC_SPRITE_TABLE: dict[int, tuple[int, int]] = {
    1:  (12,  0),  # Castle
    2:  (12,  0),  # Castle (occupied by Raubritter)
    3:  (12,  1),  # Monastery
    5:  (12,  6),  # Cave
    6:  (12,  5),  # Mine
    8:  (13,  0),  # Village  (row 13)
    9:  (12, 12),
    13: (12,  7),  # Tomb
    16: (12,  4),  # Spring
    17: (12,  9),  # Lake
    18: (12,  3),  # Shrine
    19: (12,  6),  # Cave
    20: (12, 10),  # Pagan Altar
    21: (12, 10),  # Pagan Altar (variant)
    22: (12, 13),  # Templar Castle
    23: (12, 14),  # Baphomet Castle
    24: (12,  6),  # Alpine Cave
    25: (12,  0),  # Special Castle
    26: (12,  8),  # Ruins
    # all other types → col 15 (default) handled by fallback ellipse
}


# ── Coordinate helpers ───────────────────────────────────────────────────────

def _tile_origin(tx: int, ty: int, s: int) -> tuple[int, int]:
    """Top-left corner of tile (tx, ty) bounding box in scene pixels."""
    return (tx * TW + (ty & 1) * (TW // 2)) * s, ty * VSTEP * s


def _tile_to_scene(tx: int, ty: int, s: int) -> tuple[float, float]:
    """Centre of the diamond face of tile (tx, ty) in scene pixels."""
    ox, oy = _tile_origin(tx, ty, s)
    return ox + TW * s / 2, oy + VSTEP * s + TH * s / 2


def _in_diamond(px: float, py: float, ox: int, oy: int, s: int) -> bool:
    """True if scene point (px, py) is inside the diamond face of the tile.

    Each tile sprite has a VSTEP-pixel transparent cap before the diamond face.
    The actual face centre is at oy + VSTEP*s + TH*s/2.
    """
    hw = TW * s / 2
    hh = TH * s / 2
    cx = ox + hw
    cy = oy + VSTEP * s + hh
    dx = abs(px - cx) / hw
    dy = abs(py - cy) / hh
    return dx + dy <= 1.0


def _scene_to_tile(sx: float, sy: float, s: int,
                   max_x: int, max_y: int) -> tuple[int, int]:
    """
    Convert scene pixel coordinates to the tile grid coordinate of the tile
    that is *visually on top* at that point.

    Tiles are painted top-to-bottom, so the highest row-index (ty) whose
    diamond face contains the cursor is the one that is actually visible.
    Sprites are TR=12px tall but rows step only VSTEP=4px, so up to 3 rows
    can have overlapping sprites at any y.  The diamond face (TH=8px tall)
    of at most 2 rows can overlap at any y.

    Searching HIGH → LOW and returning the first diamond hit gives the
    correct (topmost) tile rather than the tile buried underneath.
    """
    # Diamond face of row ty starts at ty*VSTEP*s + VSTEP*s (sprite has VSTEP transparent cap).
    # Inverse: ty_raw ≈ sy/(VSTEP*s) - 1.  Add +1 margin for boundary safety.
    ty_raw = max(0, int(sy / (VSTEP * s)) - 1)
    ty_hi = min(max_y - 1, ty_raw + 2)
    ty_lo = max(0, int((sy - VSTEP * s - TH * s) / (VSTEP * s)))
    best = None
    for ty in range(ty_hi, ty_lo - 1, -1):     # HIGH → LOW: topmost tile first
        stagger = (TW // 2) * s if ty & 1 else 0
        tx = int((sx - stagger) / (TW * s))
        for dtx in range(-1, 2):
            ctx = tx + dtx
            if not (0 <= ctx < max_x):
                continue
            ox, oy = _tile_origin(ctx, ty, s)
            if _in_diamond(sx, sy, ox, oy, s):
                return ctx, ty
        if best is None and 0 <= tx < max_x:
            best = (tx, ty)     # first candidate = highest row = best guess
    if best:
        return best
    return max(0, min(int(sx / (TW * s)), max_x - 1)), max(0, min(ty_raw, max_y - 1))


def _image_size(max_x: int, max_y: int, s: int) -> tuple[int, int]:
    iw = (max_x * TW + TW // 2) * s
    ih = ((max_y - 1) * VSTEP + TR) * s   # TR not TH: last row has full sprite height
    return iw, ih


# ── Sprite sheet loading ─────────────────────────────────────────────────────

def _load_sprite_sheets(dl_path: str, scale: int) -> list:
    """
    Load MAPICONS.PIC (palette 0) and MAPICON2.PIC (palette 1) from
    <dl_path>/PICS/ and return them as a list of two QPixmaps (or None).

    Each pixmap is pre-scaled to scale * original_size so individual tile
    blits can be done with simple drawPixmap() source-rect calls.
    """
    pics_dir = os.path.join(dl_path, 'PICS')
    result = []
    for fname in ('MAPICONS.PIC', 'MAPICON2.PIC'):
        fpath = os.path.join(pics_dir, fname)
        if not os.path.exists(fpath):
            result.append(None)
            continue
        try:
            from darklands.format_pic import Pic
            p = Pic(fpath)
            if not p.pic:
                result.append(None)
                continue
            rgba, w, h = p.render_rgba_bytes()
            # render_rgba_bytes writes bytes as BGRA, matching QImage Format_ARGB32
            img = QImage(rgba, w, h, QImage.Format.Format_ARGB32)
            pm = QPixmap.fromImage(img)
            if scale != 1:
                pm = pm.scaled(
                    w * scale, h * scale,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            result.append(pm)
        except Exception:
            result.append(None)
    return result


# ── Tile adjacency (col) recalculation ───────────────────────────────────────

def _recalculate_col(m: list, tx: int, ty: int) -> None:
    """
    Recompute and update the adjacency bitmask (col) for tile (tx, ty).

    Bit layout matches PureBasic Calculate_Columns():
        bit 0 = NW neighbor same type
        bit 1 = NE neighbor same type
        bit 2 = SW neighbor same type
        bit 3 = SE neighbor same type

    NW/SW: y ± 1, x + (y&1) - 1
    NE/SE: y ± 1, x + (y&1)
    """
    max_y = len(m)
    max_x = len(m[0]) if m else 0
    if not (0 <= tx < max_x and 0 <= ty < max_y):
        return
    tile = m[ty][tx]
    pal, row = tile[0], tile[1]
    s_y = ty & 1
    neighbors = [
        (ty - 1, tx + s_y - 1),  # NW  bit 0
        (ty - 1, tx + s_y),      # NE  bit 1
        (ty + 1, tx + s_y - 1),  # SW  bit 2
        (ty + 1, tx + s_y),      # SE  bit 3
    ]
    col = 0
    for bit, (ny, nx) in enumerate(neighbors):
        if 0 <= nx < max_x and 0 <= ny < max_y:
            n = m[ny][nx]
            if n[0] == pal and n[1] == row:
                col |= (1 << bit)
    m[ty][tx] = (pal, row, col)


def _recalculate_col_and_neighbors(m: list, tx: int, ty: int) -> list[tuple[int, int]]:
    """
    Recalculate col for (tx,ty) AND all 4 of its hex neighbors.
    Returns list of (tx, ty) pairs that were updated.
    """
    max_y = len(m)
    max_x = len(m[0]) if m else 0
    s_y = ty & 1
    affected = [(tx, ty),
                (tx + s_y - 1, ty - 1),
                (tx + s_y,     ty - 1),
                (tx + s_y - 1, ty + 1),
                (tx + s_y,     ty + 1)]
    updated = []
    for cx, cy in affected:
        if 0 <= cx < max_x and 0 <= cy < max_y:
            _recalculate_col(m, cx, cy)
            updated.append((cx, cy))
    return updated


# ── Rendering ────────────────────────────────────────────────────────────────

def _render_map_pixmap(m, s: int, sprite_sheets: list | None = None) -> QPixmap:
    """
    Render the tile grid.

    If sprite_sheets is provided (list of two QPixmaps), tile sprites from
    MAPICONS/MAPICON2 are blitted at correct positions.  The col adjacency
    field selects the x-column in the sprite sheet.

    Falls back to filled diamonds when sprites are unavailable.
    Rows are painted top-to-bottom so the 4px depth fringe of each sprite
    is correctly overdrawn by the next row.
    """
    max_y = len(m)
    max_x = len(m[0]) if m else 0
    iw, ih = _image_size(max_x, max_y, s)

    pm = QPixmap(iw, ih)
    pm.fill(QColor(*_MAP_BG_COLOR))

    painter = QPainter(pm)
    painter.setPen(Qt.PenStyle.NoPen)

    use_sprites = (sprite_sheets is not None and any(sp is not None for sp in sprite_sheets))
    tw_s = TW * s
    tr_s = TR * s
    th_s = TH * s

    for ty in range(max_y):
        stagger = (TW // 2) * s if ty & 1 else 0
        oy = ty * VSTEP * s
        for tx in range(max_x):
            tile = m[ty][tx]
            if tile is None:
                continue
            pal  = tile[0]
            row  = tile[1]
            col  = tile[2] if len(tile) > 2 else 0
            ox   = tx * tw_s + stagger

            if use_sprites:
                sheet = sprite_sheets[pal] if pal < len(sprite_sheets) else None
                if sheet is not None:
                    src_x = col * tw_s
                    src_y = row * tr_s
                    painter.drawPixmap(ox, oy, sheet, src_x, src_y, tw_s, tr_s)
                    continue
            # ── Fallback: filled diamond ──────────────────────────────────
            r, g, b = _TILE_COLORS[pal * 16 + row]
            hw = tw_s // 2
            hh = th_s // 2
            diamond = QPolygon([
                QPoint(ox + hw,       oy),
                QPoint(ox + tw_s,     oy + hh),
                QPoint(ox + hw,       oy + th_s),
                QPoint(ox,            oy + hh),
            ])
            painter.setBrush(QBrush(QColor(r, g, b)))
            painter.drawPolygon(diamond)

    painter.end()
    return pm


class _GridOverlay(QGraphicsItem):
    """
    Isometric diamond grid drawn on demand for the visible viewport only.

    Replaces the pre-rendered full-map pixmap approach: instead of
    alpha-compositing a ~6000×1600 transparent pixmap every frame, we draw
    only the O(viewport_width / step) lines that intersect the exposed rect.
    Positioned at (0, VSTEP*s) so lines align with the actual diamond faces.
    """

    def __init__(self, max_x: int, max_y: int, s: int):
        super().__init__()
        self._s = s
        iw, ih = _image_size(max_x, max_y, s)
        self._iw = iw
        self._ih = ih
        self.setZValue(5)
        self.setPos(0, VSTEP * s)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._iw, self._ih)

    def paint(self, painter, option, widget=None):
        step = TW * self._s
        hw   = step // 2
        ih   = self._ih

        r    = option.exposedRect
        ex1  = int(r.left())
        ey1  = int(r.top())
        ex2  = int(r.right())  + 1
        ey2  = int(r.bottom()) + 1

        painter.setPen(QPen(QColor(255, 255, 255, 60), 0))

        # Right-leaning lines pass through (x0, 0)→(x0+2*ih, ih), slope +0.5.
        # A line with offset x0 intersects the exposed rect when:
        #   ex1 - 2*ey2  <=  x0  <=  ex2 - 2*ey1
        lo = ex1 - 2 * ey2
        hi = ex2 - 2 * ey1
        x0 = hw + ((lo - hw) // step) * step
        while x0 <= hi + step:
            painter.drawLine(x0, 0, x0 + 2 * ih, ih)
            x0 += step

        # Left-leaning lines pass through (x1, 0)→(x1-2*ih, ih), slope -0.5.
        # Intersects exposed rect when:
        #   ex1 + 2*ey1  <=  x1  <=  ex2 + 2*ey2
        lo = ex1 + 2 * ey1
        hi = ex2 + 2 * ey2
        x1 = hw + ((lo - hw) // step) * step
        while x1 <= hi + step:
            painter.drawLine(x1, 0, x1 - 2 * ih, ih)
            x1 += step


def _repaint_tiles(pm: QPixmap, tiles: list[tuple[int, int]], s: int,
                   m: list, sprite_sheets: list | None = None) -> None:
    """
    In-place repaint of a specific set of tiles on an existing base pixmap.

    No explicit erase is needed.  Darklands tile sprites are fully opaque
    inside their diamond regions; re-rendering them in top-to-bottom order
    simply overwrites the old pixels with the new ones.  Transparent cap/corner
    regions are correctly filled by the neighbouring tiles that render
    before/after them — exactly the same way the initial full render works.

    Any erase step (rect or polygon) inevitably clips into pixels that belong
    to sprites from adjacent rows, creating visible artefacts that are hard to
    repair without repainting the entire map.  Omitting the erase avoids all
    of that complexity.
    """
    if not m:
        return
    max_y = len(m)
    max_x = len(m[0]) if m else 0

    tw_s = TW * s
    tr_s = TR * s
    th_s = TH * s

    use_sprites = (sprite_sheets is not None
                   and any(sp is not None for sp in sprite_sheets))

    # Deduplicate, filter out-of-bounds, sort top→bottom then left→right so
    # sprites are laid down in the same order as the initial full render.
    work = sorted(
        {(tx, ty) for tx, ty in tiles
         if 0 <= tx < max_x and 0 <= ty < max_y},
        key=lambda p: (p[1], p[0]),
    )
    if not work:
        return

    painter = QPainter(pm)
    painter.setPen(Qt.PenStyle.NoPen)

    for tx, ty in work:
        tile = m[ty][tx]
        if not tile:
            continue
        pal = tile[0]
        row = tile[1]
        col = tile[2] if len(tile) > 2 else 0
        ox, oy = _tile_origin(tx, ty, s)

        if use_sprites and pal < len(sprite_sheets) and sprite_sheets[pal]:
            painter.drawPixmap(
                ox, oy, sprite_sheets[pal],
                col * tw_s, row * tr_s, tw_s, tr_s,
            )
        else:
            idx      = pal * 16 + row
            r, g, b  = (_TILE_COLORS[idx] if idx < len(_TILE_COLORS)
                        else (128, 128, 128))
            voff     = VSTEP * s
            hw, hh   = tw_s // 2, th_s // 2
            painter.setBrush(QBrush(QColor(r, g, b)))
            painter.drawPolygon(QPolygon([
                QPoint(ox + hw,   oy + voff),
                QPoint(ox + tw_s, oy + voff + hh),
                QPoint(ox + hw,   oy + voff + th_s),
                QPoint(ox,        oy + voff + hh),
            ]))

    painter.end()


# ── Info-card HTML ───────────────────────────────────────────────────────────

def _city_flag_label(flag: str) -> str:
    try:
        from darklands.format_cty import city_content_label
        return city_content_label(flag)
    except Exception:
        return flag.replace("has_", "").replace("_", " ")


def _location_html(loc: dict, city=None, desc: str = "") -> str:
    from darklands.utils import tchars
    lines: list[str] = []
    name     = loc["name"] or "(unnamed)"
    loc_type = loc["str_loc_type"]
    cx, cy   = loc["coords"]

    lines.append(f"<h2 style='margin-bottom:4px'>{name}</h2>")
    lines.append(
        f"<p style='color:#aaa;margin-top:0'>"
        f"{loc_type} &nbsp;·&nbsp; tile ({cx}, {cy})</p>"
    )

    if city:
        lines.append(f"<h3 style='margin-bottom:4px'>{tchars(city.name)}</h3>")
        lines.append(f"<p>{city.str_city_type} &nbsp;·&nbsp; Size {city.city_size}</p>")

        yes = [
            _city_flag_label(k).title()
            for k, v in city.city_contents.items()
            if v and not k.startswith("has_constant") and k != "has_polit"
        ]
        if yes:
            lines.append("<b>Buildings:</b><br>")
            lines.append(
                " &nbsp; ".join(f"<span style='color:#8f8'>✔ {b}</span>" for b in yes)
            )

        qual_keys = [
            ("blacksmith", "Blacksmith"), ("merchant", "Merchant"),
            ("swordsmith", "Swordsmith"), ("armorer", "Armorer"),
            ("bowyer",     "Bowyer"),     ("tinker",  "Tinker"),
            ("clothing",   "Clothing"),
        ]
        qual_rows = [
            (lbl, getattr(city, f"qual_{k}", 0) or 0)
            for k, lbl in qual_keys
        ]
        qual_rows = [(lbl, q) for lbl, q in qual_rows if q]
        if qual_rows:
            lines.append("<br><b>Services:</b><table style='margin-top:4px'>")
            for lbl, q in qual_rows:
                bar = "█" * q + "░" * max(0, 5 - q)
                lines.append(
                    f"<tr><td style='padding-right:8px'>{lbl}</td>"
                    f"<td style='color:#fc0;font-family:monospace'>{bar}</td>"
                    f"<td style='color:#aaa;padding-left:4px'>{q}</td></tr>"
                )
            lines.append("</table>")

        if city.ruler_name:
            lines.append(f"<br><b>Ruler:</b> {tchars(city.ruler_name)}")
        if city.leader_name and city.leader_name != city.ruler_name:
            lines.append(f"<br><b>Leader:</b> {tchars(city.leader_name)}")
        if city.str_dock_destinations:
            lines.append(f"<br><b>Docks to:</b> {city.str_dock_destinations}")

    if desc:
        lines.append(f"<hr><p style='color:#ccc'><i>{desc}</i></p>")

    return "".join(lines)


def _build_cursor_pixmap(s: int) -> QPixmap:
    """
    Build the tile-cursor sprite at scale s.

    Pixel pattern matches the original tile_cs sprite: a 2-px-thick isometric
    diamond outline inside a TW×TR bounding box, with a VSTEP-row transparent
    cap at the top (same layout as map-tile sprites so setPos(ox, oy) aligns).
    """
    hw = TW // 2
    color_val = QColor(255, 220, 0, 255).rgba()
    img = QImage(TW, TR, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    for y in range(TR):
        # k = half-pixel-width from centre; 0 at tip, 4 at equator
        k = min(y - VSTEP, TR - y)
        if k <= 0:
            continue
        lx = hw - 2 * k          # left-edge first x
        rx = hw + 2 * k - 2      # right-edge first x
        for x in (lx, lx + 1, rx, rx + 1):
            if 0 <= x < TW:
                img.setPixel(x, y, color_val)
    pm = QPixmap.fromImage(img)
    if s != 1:
        pm = pm.scaled(TW * s, TR * s,
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.FastTransformation)
    return pm


# ── _TileCursor ───────────────────────────────────────────────────────────────

class _TileCursor(QGraphicsItem):
    """
    Isometric diamond cursor drawn over the currently hovered tile.

    Uses the same TW×TR sprite layout as map tiles so setPos(ox, oy) aligns
    the cursor exactly with the tile underneath (transparent cap included).
    Rendered at ZValue 20 so it sits above all map content.
    """

    def __init__(self, s: int):
        super().__init__()
        self._s      = s
        self._active = False
        self._pm     = _build_cursor_pixmap(s)
        self.setZValue(20)
        self.setAcceptHoverEvents(False)

    # QGraphicsItem interface ─────────────────────────────────────────────────

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, TW * self._s, TR * self._s)

    def paint(self, painter, option, widget=None):
        if self._active:
            painter.drawPixmap(0, 0, self._pm)

    # Public API ──────────────────────────────────────────────────────────────

    def move_to_tile(self, tx: int, ty: int) -> None:
        ox, oy = _tile_origin(tx, ty, self._s)
        self.setPos(ox, oy)   # transparent cap in sprite handles vertical alignment
        self._active = True
        self.update()

    def deactivate(self) -> None:
        if self._active:
            self._active = False
            self.update()


# ── _TilePalette ─────────────────────────────────────────────────────────────

class _TilePalette(QWidget):
    tile_selected = Signal(int, int)   # pal, tile_row

    _COLS      = 2   # 2 columns leaves room for the name label
    _THUMB_S   = 2   # scale for sprite thumbnails (→ 32×24 per tile)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sel_pal  = 0   # active palette (0=MAPICONS, 1=MAPICON2)
        self._sel_row  = 5   # Plains default
        self._sheets: list = []
        self._btns: list[QToolButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        hdr = QLabel("Tile Palette")
        f = hdr.font(); f.setBold(True); hdr.setFont(f)
        outer.addWidget(hdr)

        # ── Palette selector ────────────────────────────────────────────
        pal_row = QHBoxLayout()
        pal_row.setSpacing(3)
        self._pal_btns: list[QPushButton] = []
        for i, name in enumerate(("MAPICONS", "MAPICON2")):
            pb = QPushButton(name)
            pb.setCheckable(True)
            pb.setFixedHeight(22)
            pb.clicked.connect(lambda _=False, p=i: self._set_pal(p))
            pal_row.addWidget(pb)
            self._pal_btns.append(pb)
        self._pal_btns[0].setChecked(True)
        outer.addLayout(pal_row)

        # ── Tile grid ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        grid_w = QWidget()
        self._grid = QGridLayout(grid_w)
        self._grid.setSpacing(2)
        self._grid.setContentsMargins(2, 2, 2, 2)

        tw = TW * self._THUMB_S
        tr = TR * self._THUMB_S
        btn_font = QFont(); btn_font.setPointSize(7)
        for row in range(16):
            btn = QToolButton()
            btn.setFixedWidth(tw + 24)   # sprite width + padding for text
            btn.setFont(btn_font)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.clicked.connect(lambda _=False, r=row: self._on_btn(r))
            self._btns.append(btn)
            self._grid.addWidget(btn, row // self._COLS, row % self._COLS)

        scroll.setWidget(grid_w)
        outer.addWidget(scroll, stretch=1)

        self._sel_label = QLabel()
        self._sel_label.setStyleSheet("color:#fc0; font-weight:bold; font-size:9px;")
        outer.addWidget(self._sel_label)

        self._refresh()

    # ── Public API ───────────────────────────────────────────────────────

    def set_sprite_sheets(self, sheets: list) -> None:
        """Called after map load to provide actual tile sprites."""
        self._sheets = sheets or []
        self._refresh()

    @property
    def selected_tile(self) -> tuple[int, int]:
        return self._sel_pal, self._sel_row

    # ── Internals ────────────────────────────────────────────────────────

    def _set_pal(self, pal: int) -> None:
        self._sel_pal = pal
        for i, pb in enumerate(self._pal_btns):
            pb.setChecked(i == pal)
        self._refresh()
        self.tile_selected.emit(self._sel_pal, self._sel_row)

    def _on_btn(self, row: int) -> None:
        self._sel_row = row
        self._refresh()
        self.tile_selected.emit(self._sel_pal, self._sel_row)

    def _refresh(self) -> None:
        tw = TW * self._THUMB_S
        tr = TR * self._THUMB_S
        pal = self._sel_pal
        sheet = (self._sheets[pal]
                 if self._sheets and pal < len(self._sheets) else None)
        for row in range(16):
            btn  = self._btns[row]
            idx  = pal * 16 + row
            name = _TILE_NAMES[idx] if idx < len(_TILE_NAMES) else f"row {row}"
            sel  = (row == self._sel_row)
            border = "3px solid #fc0" if sel else "1px solid #444"

            if sheet is not None:
                # Use col=15 (fully-surrounded) for the richest tile preview
                sprite = sheet.copy(15 * tw, row * tr, tw, tr)
                btn.setIcon(QIcon(sprite))
                btn.setIconSize(QSize(tw, tr))
                btn.setText(name)
                btn.setToolTip(f"{name}\npal={pal}  row={row}")
                btn.setStyleSheet(f"border:{border}; padding:1px; color:#ddd;")
            else:
                # Fallback: plain colour swatch with name
                r2, g2, b2 = _TILE_COLORS[idx]
                lum = 0.299 * r2 + 0.587 * g2 + 0.114 * b2
                fg  = "#000" if lum > 128 else "#fff"
                btn.setIcon(QIcon())
                btn.setText(name)
                btn.setToolTip(f"{name}\npal={pal}  row={row}")
                btn.setStyleSheet(
                    f"background:rgb({r2},{g2},{b2});color:{fg};"
                    f"border:{border};font-size:8px;"
                )

        idx  = pal * 16 + self._sel_row
        name = _TILE_NAMES[idx] if idx < len(_TILE_NAMES) else f"row {self._sel_row}"
        self._sel_label.setText(f"Selected: {name}")


# ── _InfoPalettePanel ────────────────────────────────────────────────────────

class _InfoPalettePanel(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self.setMaximumWidth(340)

        ph = QLabel("Click a location\non the map for details.")
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setStyleSheet("color:#666; font-size:12px;")
        self.addWidget(ph)            # index 0

        self._info = QTextBrowser()
        self._info.setOpenExternalLinks(False)
        self._info.setStyleSheet("background:#1a1a1a; color:#ddd; border:none;")
        self.addWidget(self._info)    # index 1

        self.palette = _TilePalette()
        self.addWidget(self.palette)  # index 2

    def show_placeholder(self):  self.setCurrentIndex(0)
    def show_palette(self):      self.setCurrentIndex(2)

    def show_info(self, html: str):
        self._info.setHtml(html)
        self.setCurrentIndex(1)


# ── _LocationMarker ──────────────────────────────────────────────────────────

MARKER_R = 5

class _LocationMarker(QGraphicsItem):
    """
    Location pin on the world map.

    Item position = tile origin (top-left of sprite bounding box), matching
    PureBasic DisplayLocations which draws sprites at (plx, ply) = tile origin.
    Sprite draws at (0, 0) relative to item pos; fallback ellipse centers on
    the diamond face at (TW*s//2, TH*s//2).  Label floats above the diamond.
    """

    def __init__(self, loc_idx: int, loc: dict, ox: float, oy: float,
                 icon_pixmap: QPixmap | None = None, s: int = 2):
        super().__init__()
        self.loc_idx = loc_idx
        self.loc = loc
        self._s = s
        self.setPos(ox, oy)
        self._color   = _LOC_COLORS.get(loc["icon"], _LOC_COLOR_DEFAULT)
        self._pixmap  = icon_pixmap
        self.setZValue(10)
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(f"{loc['name']} ({loc['str_loc_type']})")

        self._label = QGraphicsSimpleTextItem(loc["name"], self)
        lf = QFont(); lf.setPointSize(5); lf.setBold(True)
        self._label.setFont(lf)
        self._label.setBrush(QBrush(QColor(255, 255, 220)))
        # Center label above diamond face (12 px above tile origin)
        lbl_w = self._label.boundingRect().width()
        self._label.setPos(TW * s / 2 - lbl_w / 2, -12)
        self._label.setZValue(11)
        self._label.setVisible(False)

    def boundingRect(self) -> QRectF:
        s = self._s
        if self._pixmap is not None:
            return QRectF(0, 0, TW * s, TR * s)
        cx, cy = TW * s // 2, VSTEP * s + TH * s // 2
        return QRectF(cx - MARKER_R, cy - MARKER_R, MARKER_R * 2, MARKER_R * 2)

    def paint(self, painter, option, widget=None):
        s = self._s
        if self._pixmap is not None:
            painter.drawPixmap(0, 0, self._pixmap)
        else:
            cx, cy = TW * s // 2, VSTEP * s + TH * s // 2
            painter.setPen(QPen(Qt.GlobalColor.black, 0.8))
            painter.setBrush(QBrush(self._color))
            painter.drawEllipse(cx - MARKER_R, cy - MARKER_R, MARKER_R * 2, MARKER_R * 2)

    def set_label_visible(self, v: bool):
        self._label.setVisible(v)

    def reposition(self, ox: float, oy: float):
        self.setPos(ox, oy)


# ── _MapScene ────────────────────────────────────────────────────────────────

class _MapScene(QGraphicsScene):
    location_clicked    = Signal(int)
    tile_clicked        = Signal(int, int)
    hovered_tile        = Signal(int, int)
    paint_stroke_started = Signal()   # emitted once on left-press in edit mode
    paint_stroke_ended   = Signal()   # emitted once on left-release in edit mode

    def __init__(self):
        super().__init__()
        self.edit_mode = False
        self.scale     = 2
        self.max_x     = 0
        self.max_y     = 0

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        sp = event.scenePos()
        if not self.edit_mode:
            for item in self.items(sp):
                if isinstance(item, _LocationMarker):
                    self.location_clicked.emit(item.loc_idx)
                    event.accept()
                    return
        else:
            tx, ty = _scene_to_tile(sp.x(), sp.y(), self.scale,
                                    self.max_x, self.max_y)
            self.paint_stroke_started.emit()
            self.tile_clicked.emit(tx, ty)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.edit_mode and event.button() == Qt.MouseButton.LeftButton:
            self.paint_stroke_ended.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        sp = event.scenePos()
        tx, ty = _scene_to_tile(sp.x(), sp.y(), self.scale,
                                 self.max_x, self.max_y)
        ox, oy = _tile_origin(tx, ty, self.scale)
        if _in_diamond(sp.x(), sp.y(), ox, oy, self.scale):
            self.hovered_tile.emit(tx, ty)
            # Paint while dragging in edit mode (left button held)
            if self.edit_mode and (event.buttons() & Qt.MouseButton.LeftButton):
                self.tile_clicked.emit(tx, ty)
        else:
            self.hovered_tile.emit(-1, -1)
        super().mouseMoveEvent(event)


# ── _MapView ─────────────────────────────────────────────────────────────────

class _MapView(QGraphicsView):
    def __init__(self, scene: _MapScene):
        super().__init__(scene)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setBackgroundBrush(QBrush(QColor(*_MAP_BG_COLOR)))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._drag_pos: QPoint | None = None      # left-button pan (view mode)
        self._mid_drag_pos: QPoint | None = None  # middle-button pan (any mode)

    def wheelEvent(self, event):
        delta  = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale(factor, factor)

    def set_edit_cursor(self, edit: bool):
        self._drag_pos = None
        self._mid_drag_pos = None
        if edit:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        else:
            self.unsetCursor()

    def _pan(self, new_pos: QPoint, old_pos: QPoint) -> None:
        delta = new_pos - old_pos
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - delta.x()
        )
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - delta.y()
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            # Middle-button drag pans in both view and edit modes
            self._mid_drag_pos = event.pos()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self.scene().edit_mode:
            self._drag_pos = event.pos()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._mid_drag_pos is not None:
            self._pan(event.pos(), self._mid_drag_pos)
            self._mid_drag_pos = event.pos()
        elif self._drag_pos is not None:
            self._pan(event.pos(), self._drag_pos)
            self._drag_pos = event.pos()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._mid_drag_pos is not None:
            self._mid_drag_pos = None
            # Restore the cursor that was active before panning
            if self.scene().edit_mode:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            else:
                self.unsetCursor()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self._drag_pos = None
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def fit_all(self):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


# ── MapEditorWidget ──────────────────────────────────────────────────────────

class MapEditorWidget(QWidget):
    """Drop-in replacement for MapConverter — full viewer/editor."""

    SCALES = [1, 2, 3]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dl_path = ""

        self._map_data  = None
        self._locs:   list[dict] = []
        self._cities: list      = []
        self._city_by_name: dict[str, object] = {}
        self._descs:  list[str] = []

        self._scale         = 2
        self._edit_mode     = False
        self._dirty         = False
        self._needs_refresh = True
        self._sprite_sheets: list = [None, None]

        self._base_pixmap: QPixmap | None = None
        self._base_item:   QGraphicsPixmapItem | None = None
        self._grid_item:   QGraphicsPixmapItem | None = None
        self._cursor_item: _TileCursor | None = None
        self._markers:     list[_LocationMarker] = []

        # Undo — each entry is {(tx,ty): old_tile, ...} for one paint stroke
        self._undo_stack: list[dict] = []
        self._stroke_pre: dict       = {}  # tiles touched before this stroke

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 4)
        root.setSpacing(4)

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._chk_labels = QCheckBox("Labels")
        self._chk_labels.setChecked(True)
        self._chk_labels.toggled.connect(self._on_labels_toggled)
        toolbar.addWidget(self._chk_labels)

        self._chk_icons = QCheckBox("Icons")
        self._chk_icons.setChecked(True)
        self._chk_icons.toggled.connect(self._on_icons_toggled)
        toolbar.addWidget(self._chk_icons)

        self._chk_grid = QCheckBox("Grid")
        self._chk_grid.setChecked(False)
        self._chk_grid.toggled.connect(self._on_grid_toggled)
        toolbar.addWidget(self._chk_grid)

        toolbar.addWidget(_vsep())

        self._mode_btn = QPushButton("✏  Edit Mode")
        self._mode_btn.setCheckable(True)
        self._mode_btn.setFixedWidth(100)
        self._mode_btn.toggled.connect(self._on_mode_toggled)
        toolbar.addWidget(self._mode_btn)

        toolbar.addWidget(_vsep())

        self._undo_btn = QPushButton("⎌  Undo")
        self._undo_btn.setEnabled(False)
        self._undo_btn.setFixedWidth(80)
        self._undo_btn.setToolTip("Undo last paint stroke  (Ctrl+Z)")
        self._undo_btn.clicked.connect(self._undo)
        toolbar.addWidget(self._undo_btn)

        self._save_btn = QPushButton("💾  Save Map")
        self._save_btn.setEnabled(False)
        self._save_btn.setFixedWidth(100)
        self._save_btn.clicked.connect(self._save_map)
        toolbar.addWidget(self._save_btn)

        self._revert_btn = QPushButton("↺  Revert")
        self._revert_btn.setEnabled(False)
        self._revert_btn.setFixedWidth(80)
        self._revert_btn.clicked.connect(self._revert_map)
        toolbar.addWidget(self._revert_btn)

        toolbar.addStretch()

        fit_btn = QPushButton("⊡  Fit")
        fit_btn.setFixedWidth(60)
        fit_btn.setToolTip("Fit whole map in view")
        fit_btn.clicked.connect(lambda: self._view.fit_all())
        toolbar.addWidget(fit_btn)

        root.addLayout(toolbar)

        # ── Splitter ─────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._scene = _MapScene()
        self._scene.location_clicked.connect(self._on_location_clicked)
        self._scene.tile_clicked.connect(self._on_tile_clicked)
        self._scene.hovered_tile.connect(self._on_tile_hovered)
        self._scene.paint_stroke_started.connect(self._on_paint_started)
        self._scene.paint_stroke_ended.connect(self._on_paint_ended)

        # Ctrl+Z undo shortcut (active whenever this widget is focused)
        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self._undo)

        self._view = _MapView(self._scene)
        splitter.addWidget(self._view)

        self._panel = _InfoPalettePanel()
        self._panel.palette.tile_selected.connect(self._on_tile_selected)
        splitter.addWidget(self._panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([860, 280])

        root.addWidget(splitter, stretch=1)

        # ── Status bar ───────────────────────────────────────────────────
        self._status = QLabel("Set the DL data path to load the map.")
        self._status.setStyleSheet("color:#888; font-size:10px;")
        root.addWidget(self._status)

    # ── Path / lazy load ─────────────────────────────────────────────────

    def set_dl_path(self, path: str):
        if path == self.dl_path:
            return
        self.dl_path = path
        self._map_data = None
        self._needs_refresh = True
        if path and self.isVisible():
            QTimer.singleShot(50, self._load_and_rebuild)

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_refresh and self.dl_path:
            self._needs_refresh = False
            QTimer.singleShot(50, self._load_and_rebuild)

    # ── Data loading ─────────────────────────────────────────────────────

    def _load_and_rebuild(self):
        self._status.setText("Loading map data…")
        QApplication.processEvents()
        try:
            from darklands.reader_map import readData as read_map
            from darklands.reader_loc import readData as read_loc
            from darklands.format_cty import readData as read_cty
            from darklands.format_dsc import readData as read_dsc

            self._map_data = read_map(self.dl_path)

            try:   self._locs = read_loc(self.dl_path)
            except Exception: self._locs = []

            try:
                self._cities = read_cty(self.dl_path)
                self._city_by_name = {
                    c.short_name.strip().lower(): c for c in self._cities
                }
                for c in self._cities:
                    from darklands.utils import tchars
                    self._city_by_name[tchars(c.name).strip().lower()] = c
            except Exception:
                self._cities = []
                self._city_by_name = {}

            try:   self._descs = read_dsc(self.dl_path)
            except Exception: self._descs = []

            # Load tile sprite sheets
            self._status.setText("Loading tile sprites…")
            QApplication.processEvents()
            try:
                self._sprite_sheets = _load_sprite_sheets(self.dl_path, self._scale)
                n_loaded = sum(1 for sp in self._sprite_sheets if sp is not None)
                sprite_note = f"  ·  {n_loaded}/2 sprite sheets" if n_loaded else "  ·  no sprites (fallback colours)"
            except Exception:
                self._sprite_sheets = [None, None]
                sprite_note = "  ·  sprite load failed"

            self._panel.palette.set_sprite_sheets(self._sprite_sheets)
            self._rebuild_scene()
            self._dirty = False
            self._undo_stack.clear()
            self._stroke_pre.clear()
            self._save_btn.setEnabled(False)
            self._revert_btn.setEnabled(False)
            self._undo_btn.setEnabled(False)

            h = len(self._map_data)
            w = len(self._map_data[0]) if self._map_data else 0
            self._status.setText(
                f"Map {w}×{h}  ·  {len(self._locs)} locations  ·  "
                f"{len(self._cities)} cities{sprite_note}  ·  wheel=zoom  drag=pan"
            )
            QTimer.singleShot(100, self._view.fit_all)
        except Exception:
            self._status.setText("Error loading map — check DL path.")
            self._scene.clear()

    # ── Scene construction ───────────────────────────────────────────────

    def _rebuild_scene(self):
        self._scene.clear()
        self._markers.clear()
        self._base_item   = None
        self._grid_item   = None
        self._cursor_item = None

        if not self._map_data:
            return

        max_y = len(self._map_data)
        max_x = len(self._map_data[0])
        s = self._scale

        self._scene.scale = s
        self._scene.max_x = max_x
        self._scene.max_y = max_y

        # Base map
        self._status.setText("Rendering map…")
        QApplication.processEvents()
        self._base_pixmap = _render_map_pixmap(self._map_data, s, self._sprite_sheets)
        self._base_item   = QGraphicsPixmapItem(self._base_pixmap)
        self._base_item.setZValue(0)
        self._scene.addItem(self._base_item)

        # Grid overlay — draws only lines visible in the current viewport
        self._grid_item = _GridOverlay(max_x, max_y, s)
        self._grid_item.setVisible(self._chk_grid.isChecked())
        self._scene.addItem(self._grid_item)

        # Isometric cursor (always in scene, activated on first hover)
        self._cursor_item = _TileCursor(s)
        self._scene.addItem(self._cursor_item)

        # Location markers
        show_labels = self._chk_labels.isChecked()
        show_icons  = self._chk_icons.isChecked()
        sheet2 = self._sprite_sheets[1] if len(self._sprite_sheets) > 1 else None
        tw_s, tr_s = TW * s, TR * s
        for i, loc in enumerate(self._locs):
            tx, ty = loc["coords"]
            ox, oy = _tile_origin(tx, ty, s)
            icon_pm = None
            if sheet2 is not None:
                entry = _LOC_SPRITE_TABLE.get(loc.get("icon", -1))
                if entry is not None:
                    srow, scol = entry
                    icon_pm = sheet2.copy(scol * tw_s, srow * tr_s, tw_s, tr_s)
            marker = _LocationMarker(i, loc, ox, oy, icon_pm, s)
            marker.set_label_visible(show_labels)
            marker.setVisible(show_icons)
            self._scene.addItem(marker)
            self._markers.append(marker)

        iw, ih = _image_size(max_x, max_y, s)
        self._scene.setSceneRect(QRectF(0, 0, iw, ih))

    # ── Overlay toggles ──────────────────────────────────────────────────

    def _on_labels_toggled(self, checked: bool):
        for m in self._markers:
            m.set_label_visible(checked)

    def _on_icons_toggled(self, checked: bool):
        for m in self._markers:
            m.setVisible(checked)

    def _on_grid_toggled(self, checked: bool):
        if self._grid_item:
            self._grid_item.setVisible(checked)

    # ── Mode toggle ──────────────────────────────────────────────────────

    def _on_mode_toggled(self, edit: bool):
        self._edit_mode = edit
        self._scene.edit_mode = edit
        self._view.set_edit_cursor(edit)
        self._mode_btn.setText("👁  View Mode" if edit else "✏  Edit Mode")
        if edit:
            self._panel.show_palette()
        else:
            self._panel.show_placeholder()

    # ── Location info ─────────────────────────────────────────────────────

    def _on_location_clicked(self, loc_idx: int):
        if loc_idx >= len(self._locs):
            return
        loc  = self._locs[loc_idx]
        city = self._city_by_name.get(loc["name"].strip().lower())
        desc = self._descs[loc_idx] if loc_idx < len(self._descs) else ""
        self._panel.show_info(_location_html(loc, city, desc))
        tx, ty = loc["coords"]
        self._status.setText(
            f"{loc['name']}  ({loc['str_loc_type']})  tile ({tx}, {ty})"
        )

    # ── Hover ────────────────────────────────────────────────────────────

    def _on_tile_hovered(self, tx: int, ty: int):
        if not self._map_data:
            return
        if tx < 0:
            if self._cursor_item:
                self._cursor_item.deactivate()
            return
        h, w = len(self._map_data), len(self._map_data[0])
        if 0 <= ty < h and 0 <= tx < w:
            tile = self._map_data[ty][tx]
            if tile:
                idx  = tile[0] * 16 + tile[1]
                if idx == 0:
                    if self._cursor_item:
                        self._cursor_item.deactivate()
                    return
                if self._cursor_item:
                    self._cursor_item.move_to_tile(tx, ty)
                name = _TILE_NAMES[idx] if idx < len(_TILE_NAMES) else "?"
                col  = tile[2] if len(tile) > 2 else 0
                dirty = " ✎" if self._dirty else ""
                self._status.setText(f"({tx}, {ty})  ·  {name}  col={col:#06b}{dirty}")
            else:
                if self._cursor_item:
                    self._cursor_item.deactivate()

    # ── Tile editor ──────────────────────────────────────────────────────

    def _on_tile_selected(self, pal: int, row: int):
        pass   # selection is read directly from _panel.palette.selected_tile

    # ── Paint-stroke undo tracking ───────────────────────────────────────

    def _on_paint_started(self):
        """Called at the start of every left-click paint stroke."""
        self._stroke_pre.clear()

    def _on_paint_ended(self):
        """Called when the mouse button is released after a paint stroke."""
        if self._stroke_pre:
            self._undo_stack.append(dict(self._stroke_pre))
            self._stroke_pre.clear()
            if len(self._undo_stack) > 50:      # cap history depth
                self._undo_stack.pop(0)
            self._undo_btn.setEnabled(True)

    def _undo(self):
        """Undo the most recent paint stroke."""
        if not self._undo_stack or not self._map_data:
            return
        stroke = self._undo_stack.pop()

        # Restore each tile to its pre-stroke state
        for (tx, ty), old_tile in stroke.items():
            self._map_data[ty][tx] = old_tile

        # Recalculate col for every restored tile and all their neighbours
        all_updated: set[tuple[int, int]] = set()
        for tx, ty in stroke:
            for pt in _recalculate_col_and_neighbors(self._map_data, tx, ty):
                all_updated.add(pt)

        # Repaint
        if self._base_pixmap:
            _repaint_tiles(self._base_pixmap, list(all_updated),
                           self._scale, self._map_data, self._sprite_sheets)
            if self._base_item:
                self._base_item.setPixmap(self._base_pixmap)

        # Undo button state
        self._undo_btn.setEnabled(bool(self._undo_stack))

        # Dirty state — no longer dirty if undo stack is empty
        if not self._undo_stack:
            self._dirty = False
            self._save_btn.setEnabled(False)
            self._revert_btn.setEnabled(False)

    # ── Tile click / drag paint ──────────────────────────────────────────

    def _on_tile_clicked(self, tx: int, ty: int):
        if not self._edit_mode or not self._map_data:
            return
        h, w = len(self._map_data), len(self._map_data[0])
        if not (0 <= tx < w and 0 <= ty < h):
            return

        new_pal, new_row = self._panel.palette.selected_tile
        old = self._map_data[ty][tx]
        # Skip if tile already has the target type (covers drag-over-same-tile)
        if old[0] == new_pal and old[1] == new_row:
            return

        # Record pre-stroke state for undo (only the first touch of each tile)
        key = (tx, ty)
        if key not in self._stroke_pre:
            self._stroke_pre[key] = old

        # Apply new tile type (col=0 temporarily; recalculation follows)
        self._map_data[ty][tx] = (new_pal, new_row, 0)

        # Recalculate adjacency for this tile and its 4 hex neighbours
        updated = _recalculate_col_and_neighbors(self._map_data, tx, ty)

        # Repaint affected tiles top-to-bottom (no erase needed — sprites are
        # opaque in their diamond regions and simply overwrite old pixels).
        if self._base_pixmap:
            _repaint_tiles(self._base_pixmap, updated,
                           self._scale, self._map_data, self._sprite_sheets)
            if self._base_item:
                self._base_item.setPixmap(self._base_pixmap)

        if not self._dirty:
            self._dirty = True
            self._save_btn.setEnabled(True)
            self._revert_btn.setEnabled(True)

    # ── Save / revert ────────────────────────────────────────────────────

    def _save_map(self):
        if not self._map_data or not self.dl_path:
            return
        default = os.path.join(self.dl_path, "DARKLAND.MAP")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save MAP file", default, "MAP Files (*.MAP);;All Files (*)"
        )
        if not path:
            return
        try:
            from darklands.writer_map import writeData
            writeData(path, self._map_data)
            self._dirty = False
            self._save_btn.setEnabled(False)
            self._revert_btn.setEnabled(False)
            self._status.setText(f"Saved → {path}")
        except Exception:
            self._status.setText(
                "Save failed: " + traceback.format_exc().splitlines()[-1]
            )

    def _revert_map(self):
        if not self.dl_path:
            return
        self._needs_refresh = True
        self._load_and_rebuild()


# ── helpers ──────────────────────────────────────────────────────────────────

def _vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep
