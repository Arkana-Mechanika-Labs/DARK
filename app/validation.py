from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


@dataclass
class ValidationIssue:
    severity: str
    scope: str
    message: str
    detail: str = ""


@dataclass
class ValidationReport:
    issues: list[ValidationIssue]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]


def _add(issues: list[ValidationIssue], severity: str, scope: str, message: str, detail: str = ""):
    issues.append(ValidationIssue(severity, scope, message, detail))


def _safe_read(dl_path: str, filename: str) -> bytes | None:
    path = os.path.join(dl_path, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _load_catalog_names(dl_path: str, cat_name: str) -> set[str]:
    path = os.path.join(dl_path, cat_name)
    if not os.path.isfile(path):
        return set()
    try:
        from darklands.extract_cat import listContents
        return {name.upper() for name, _size, _offs in listContents(path)}
    except Exception:
        return set()


def _load_defaults(dl_path: str, overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    data = {}

    if "cities" in overrides:
        data["cities"] = overrides["cities"]
    else:
        try:
            from darklands.format_cty import readData as read_cty
            data["cities"] = read_cty(dl_path)
        except Exception:
            data["cities"] = None

    if "locations" in overrides:
        data["locations"] = overrides["locations"]
    else:
        try:
            from darklands.reader_loc import readData as read_loc
            data["locations"] = read_loc(dl_path)
        except Exception:
            data["locations"] = None

    if "descs" in overrides:
        data["descs"] = overrides["descs"]
    else:
        try:
            from darklands.format_dsc import readData as read_dsc
            data["descs"] = read_dsc(dl_path)
        except Exception:
            data["descs"] = None

    if "items" in overrides or "saints" in overrides or "formulae" in overrides:
        data["items"] = overrides.get("items")
        data["saints"] = overrides.get("saints")
        data["formulae"] = overrides.get("formulae")
    else:
        try:
            from darklands.reader_lst import readData as read_lst
            items, saints, formulae = read_lst(dl_path)
            data["items"] = items
            data["saints"] = saints
            data["formulae"] = formulae
        except Exception:
            data["items"] = data["saints"] = data["formulae"] = None

    if "enemy_types" in overrides or "enemies" in overrides:
        data["enemy_types"] = overrides.get("enemy_types")
        data["enemies"] = overrides.get("enemies")
    else:
        try:
            from darklands.reader_enm import readData as read_enm
            enemy_types, enemies = read_enm(dl_path)
            data["enemy_types"] = enemy_types
            data["enemies"] = enemies
        except Exception:
            data["enemy_types"] = data["enemies"] = None

    if "msg_cards" in overrides:
        data["msg_cards"] = overrides["msg_cards"]
        data["msg_name"] = overrides.get("msg_name", "<MSG>")
        data["msg_catalog"] = overrides.get("msg_catalog", "")
    else:
        data["msg_cards"] = None
        data["msg_name"] = ""
        data["msg_catalog"] = ""

    if "enemypal" in overrides:
        data["enemypal"] = overrides["enemypal"]
    else:
        try:
            from darklands.reader_enemypal import readData as read_enemypal
            data["enemypal"] = read_enemypal(dl_path)
        except Exception:
            data["enemypal"] = None

    data["e_cat_names"] = _load_catalog_names(dl_path, "E00C.CAT")
    data["m_cat_names"] = _load_catalog_names(dl_path, "M00C.CAT")
    data["msgfiles_names"] = _load_catalog_names(dl_path, "MSGFILES")
    return data


def validate_world_data(dl_path: str, overrides: dict | None = None) -> ValidationReport:
    data = _load_defaults(dl_path, overrides)
    issues: list[ValidationIssue] = []

    cities = data.get("cities") or []
    locations = data.get("locations") or []
    descs = data.get("descs") or []
    items = data.get("items") or []
    enemy_types = data.get("enemy_types") or []
    enemies = data.get("enemies") or []
    enemypal = data.get("enemypal") or []

    if cities:
        if len(cities) != 92:
            _add(issues, "warning", "CTY", f"Expected 92 cities from the KB, found {len(cities)}.")
        for idx, city in enumerate(cities):
            for dock_idx, target in enumerate(getattr(city, "dock_destinations", [])[:4]):
                if target not in (-1, 0xFFFF) and not (0 <= target < len(cities)):
                    _add(
                        issues,
                        "error",
                        "CTY",
                        f"City #{idx} has invalid dock destination #{dock_idx + 1}: {target}.",
                        getattr(city, "name", "") or getattr(city, "short_name", ""),
                    )

    if descs:
        if len(descs) != 92:
            _add(issues, "warning", "DSC", f"Expected 92 city descriptions from the KB, found {len(descs)}.")
        if cities and len(descs) != len(cities):
            _add(
                issues,
                "error",
                "CTY/DSC",
                f"City count ({len(cities)}) does not match description count ({len(descs)}).",
                "The KB notes DARKLAND.DSC's stored header count is wrong, but the actual entry array should still align with CTY.",
            )

    if locations:
        if len(locations) != 0x19E:
            _add(issues, "warning", "LOC", f"Expected 414 locations from the KB, found {len(locations)}.")
        city_locs = [loc for loc in locations if int(loc.get("icon", -1)) == 0]
        if cities and len(city_locs) != len(cities):
            _add(
                issues,
                "warning",
                "LOC/CTY",
                f"City-icon location count ({len(city_locs)}) does not match city count ({len(cities)}).",
            )

    if enemy_types:
        item_count = len(items)
        palette_count = len(enemypal)
        e_cat = data.get("e_cat_names", set())
        m_cat = data.get("m_cat_names", set())
        for idx, et in enumerate(enemy_types):
            image_group = (et.get("image_group", "") or "").upper()
            if image_group.startswith("E"):
                pool = e_cat
            elif image_group.startswith("M"):
                pool = m_cat
            else:
                pool = set()
            if image_group and pool and not any(name.startswith(image_group) and name.endswith(".IMC") for name in pool):
                _add(issues, "warning", "ENM", f"Enemy type #{idx} image group '{image_group}' has no matching IMC in the CAT files.")
            pal_start = int(et.get("pal_start", 0))
            pal_cnt = int(et.get("pal_cnt", 0))
            if pal_cnt <= 0:
                _add(issues, "warning", "ENM", f"Enemy type #{idx} palette count is zero.")
            elif palette_count and pal_start > 0 and (pal_start + pal_cnt - 1) > palette_count:
                _add(
                    issues,
                    "warning",
                    "ENM/ENEMYPAL",
                    f"Enemy type #{idx} palette range {pal_start}-{pal_start + pal_cnt - 1} exceeds ENEMYPAL chunk count {palette_count}.",
                )
            for field in ("vital_arm_type", "limb_arm_typetype", "shield_type"):
                value = int(et.get(field, 0xFF))
                if value != 0xFF and item_count and not (0 <= value < item_count):
                    _add(issues, "error", "ENM/LST", f"Enemy type #{idx} has invalid {field} item id {value}.")
            for slot, value in enumerate(et.get("weapon_types", b"")[:6]):
                value = int(value)
                if value != 0xFF and item_count and not (0 <= value < item_count):
                    _add(issues, "error", "ENM/LST", f"Enemy type #{idx} has invalid weapon_types[{slot}] item id {value}.")

    if enemies and enemy_types:
        for idx, enemy in enumerate(enemies):
            type_idx = int(enemy.get("type", -1))
            if not (0 <= type_idx < len(enemy_types)):
                _add(issues, "error", "ENM", f"Encounter #{idx} references invalid enemy type {type_idx}.")

    cards = data.get("msg_cards")
    if cards is not None:
        issues.extend(validate_msg_cards(cards, data.get("msg_name") or "<MSG>", data.get("msgfiles_names", set())).issues)

    return ValidationReport(issues)


def validate_msg_cards(cards: list[dict], msg_name: str, msgfiles_names: Iterable[str] | None = None) -> ValidationReport:
    issues: list[ValidationIssue] = []
    msgfiles_names = {name.upper() for name in (msgfiles_names or [])}
    valid_kinds = {"STD", "PTN", "SNT", "BTL"}
    if not cards:
        _add(issues, "warning", "MSG", f"{msg_name} contains no cards.")
        return ValidationReport(issues)
    for idx, card in enumerate(cards):
        if int(card.get("textMaxX", 0)) < int(card.get("textOffsX", 0)):
            _add(issues, "error", "MSG", f"{msg_name} card #{idx} has textMaxX before textOffsX.")
        elems = card.get("elements", [])
        if not elems:
            _add(issues, "warning", "MSG", f"{msg_name} card #{idx} has no elements.")
        option_count = 0
        for elem_idx, elem in enumerate(elems):
            if isinstance(elem, str):
                continue
            if not isinstance(elem, (list, tuple)) or not elem:
                _add(issues, "error", "MSG", f"{msg_name} card #{idx} element #{elem_idx} is not a valid text/option entry.")
                continue
            kind = str(elem[0]).upper()
            if kind not in valid_kinds:
                _add(issues, "error", "MSG", f"{msg_name} card #{idx} has unknown option kind '{kind}'.")
            else:
                option_count += 1
        if option_count > 10:
            _add(issues, "warning", "MSG", f"{msg_name} card #{idx} has more than 10 options.")
    if msg_name and msg_name.upper().endswith(".MSG") and msgfiles_names and msg_name.upper() not in msgfiles_names:
        _add(issues, "warning", "MSGFILES", f"{msg_name} is not present in MSGFILES.")
    return ValidationReport(issues)


def filter_issues(report: ValidationReport, scopes: Iterable[str]) -> list[ValidationIssue]:
    prefixes = tuple(scopes)
    return [issue for issue in report.issues if issue.scope.startswith(prefixes)]


def summarize_issues(issues: list[ValidationIssue], max_lines: int = 8) -> str:
    if not issues:
        return "No validation issues."
    lines = []
    for issue in issues[:max_lines]:
        prefix = "Error" if issue.severity == "error" else "Warning"
        lines.append(f"{prefix}: [{issue.scope}] {issue.message}")
        if issue.detail:
            lines.append(f"  {issue.detail}")
    extra = len(issues) - max_lines
    if extra > 0:
        lines.append(f"... and {extra} more.")
    return "\n".join(lines)
