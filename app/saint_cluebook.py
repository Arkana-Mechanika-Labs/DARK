from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


_ENTRY_RE = re.compile(
    r"^(?P<name>.+?)\s+\[(?P<virtue>\d+)v,\s*(?P<df_min>\d+)-(?P<df_max>\d+)df,\s*(?P<base>\d+)%\]:\s*(?P<effects>.+)$"
)

_TEXT_FIXES = {
    "Ã¢â‚¬â„¢": "'",
    "Ã¢â‚¬â€": "-",
    "Ã¢â‚¬â€œ": "-",
    "Ã¢â‚¬Â¦": "...",
    "Ã¢â‚¬": '"',
    "Ã¢â‚¬Å“": '"',
    "Ã¢â‚¬\x9d": '"',
    "Ã¢â‚¬\x98": "'",
    "Ã¢â‚¬\x99": "'",
    "ÃƒÂ©": "Ã©",
    "ÃƒÂ¶": "Ã¶",
}


def _asset_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "saints_cluebook.txt"


def _clean_text(text: str) -> str:
    for src, dst in _TEXT_FIXES.items():
        text = text.replace(src, dst)
    text = text.replace("skil1", "skill")
    text = text.replace("tbe", "the")
    text = text.replace("parry", "party")
    text = text.replace("lot +", "Int +")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" +(", " +(")
    return text


def normalize_saint_name(name: str) -> str:
    text = _clean_text(name).lower()
    text = text.replace("st.", "")
    text = text.replace("saint ", "")
    text = text.replace("astonish.", "astonishing")
    text = text.replace("o'n", "o n")
    text = text.replace("o'", "o ")
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


@lru_cache(maxsize=1)
def load_saint_cluebook() -> dict:
    path = _asset_path()
    raw = path.read_text(encoding="utf-8", errors="replace")

    entries: list[dict] = []
    notes: list[str] = []
    in_notes = False

    for raw_line in raw.splitlines():
        line = _clean_text(raw_line)
        if not line:
            continue
        if line == "Notes":
            in_notes = True
            continue
        if in_notes:
            notes.append(line)
            continue
        if len(line) == 1 and line.isalpha():
            continue

        match = _ENTRY_RE.match(line)
        if not match:
            continue

        data = match.groupdict()
        entry = {
            "name": data["name"],
            "virtue_required": int(data["virtue"]),
            "df_min": int(data["df_min"]),
            "df_max": int(data["df_max"]),
            "base_success_percent": int(data["base"]),
            "effects": _clean_text(data["effects"]),
            "summary": (
                f"Virtue {data['virtue']} - DF {data['df_min']}-{data['df_max']} - "
                f"Base {data['base']}%"
            ),
        }
        entries.append(entry)

    by_name = {normalize_saint_name(entry["name"]): entry for entry in entries}
    by_name.pop("nicolas of tolentino", None)
    return {
        "entries": entries,
        "by_name": by_name,
        "notes": notes,
    }


def saint_clue_entry(name: str) -> dict | None:
    return load_saint_cluebook()["by_name"].get(normalize_saint_name(name))


def saint_clue_notes() -> list[str]:
    return list(load_saint_cluebook()["notes"])
