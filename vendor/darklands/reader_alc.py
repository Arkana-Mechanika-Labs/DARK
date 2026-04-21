import os
import struct

from .utils import cstrim, encode_dl_bytes


FORMULA_SIZE = 0x68
DESC_SIZE = 0x50
INGREDIENT_SLOTS = 5


def _decode_formula(data: bytes, index: int) -> dict:
    description = cstrim(data[:DESC_SIZE])
    mystic_number, risk_factor = struct.unpack_from("<HH", data, DESC_SIZE)
    ingredients = []
    offs = DESC_SIZE + 4
    for slot in range(INGREDIENT_SLOTS):
        quantity, item_code = struct.unpack_from("<HH", data, offs + slot * 4)
        ingredients.append({
            "quantity": int(quantity),
            "item_code": int(item_code),
        })
    return {
        "index": index,
        "description": description,
        "mystic_number": int(mystic_number),
        "risk_factor": int(risk_factor),
        "ingredients": ingredients,
    }


def read_bytes(data: bytes) -> list[dict]:
    if not data:
        return []
    count = data[0]
    needed = 1 + count * FORMULA_SIZE
    if len(data) < needed:
        raise ValueError(f"DARKLAND.ALC is truncated: expected at least {needed} bytes, got {len(data)}.")
    formulas = []
    for idx in range(count):
        base = 1 + idx * FORMULA_SIZE
        formulas.append(_decode_formula(data[base:base + FORMULA_SIZE], idx))
    return formulas


def read_file(path: str) -> list[dict]:
    with open(path, "rb") as fh:
        return read_bytes(fh.read())


def readData(dlPath: str) -> list[dict]:
    return read_file(os.path.join(dlPath, "DARKLAND.ALC"))


def _encode_formula(formula: dict) -> bytes:
    out = bytearray()
    desc = encode_dl_bytes(formula.get("description", "") or "")[:DESC_SIZE - 1]
    out += desc.ljust(DESC_SIZE, b"\x00")
    out += struct.pack(
        "<HH",
        int(formula.get("mystic_number", 0)) & 0xFFFF,
        int(formula.get("risk_factor", 0)) & 0xFFFF,
    )
    ingredients = list(formula.get("ingredients", [])[:INGREDIENT_SLOTS])
    while len(ingredients) < INGREDIENT_SLOTS:
        ingredients.append({"quantity": 0, "item_code": 0})
    for ing in ingredients:
        out += struct.pack(
            "<HH",
            int(ing.get("quantity", 0)) & 0xFFFF,
            int(ing.get("item_code", 0)) & 0xFFFF,
        )
    return bytes(out)


def write_bytes(formulae: list[dict]) -> bytes:
    out = bytearray([len(formulae) & 0xFF])
    for formula in formulae:
        out += _encode_formula(formula)
    return bytes(out)


def write_file(path: str, formulae: list[dict]):
    with open(path, "wb") as fh:
        fh.write(write_bytes(formulae))


def writeData(dlPath: str, formulae: list[dict]):
    write_file(os.path.join(dlPath, "DARKLAND.ALC"), formulae)
