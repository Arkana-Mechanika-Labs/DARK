# coding=utf-8
# Source: vvendigo/Darklands (MIT) - modernized shared string helpers

_DL_SPECIAL_DECODE = {
    "|": "\u00fc",       # ü
    "{": "\u00f6",       # ö
    chr(0x1F): "\u00e6", # æ
}

_DL_SPECIAL_ENCODE = {value: key for key, value in _DL_SPECIAL_DECODE.items()}


def bread(d):
    """Read multibyte int (in DL common order)."""
    out = d[-1]
    for n in reversed(d[:-1]):
        out = (out << 8) | n
    return out


def rbread(d):
    """Read multibyte int (in reversed order)."""
    out = d[0]
    for n in d[1:]:
        out = (out << 8) | n
    return out


def decode_dl_text(text: str) -> str:
    if not text:
        return ""
    return "".join(_DL_SPECIAL_DECODE.get(ch, ch) for ch in text)


def encode_dl_text(text: str) -> str:
    if not text:
        return ""
    return "".join(_DL_SPECIAL_ENCODE.get(ch, ch) for ch in text)


def encode_dl_bytes(text: str, encoding: str = "latin-1", errors: str = "replace") -> bytes:
    return encode_dl_text(text).encode(encoding, errors=errors)


def sread(d):
    """Read a null-terminated Darklands string and decode special characters."""
    out = []
    for b in d:
        if b == 0:
            break
        out.append(chr(b))
    return decode_dl_text("".join(out))


def tchars(txt):
    """Translate Darklands placeholder characters to display text."""
    return decode_dl_text(txt)


def cstrim(txt):
    """Trim and decode a C-string using Darklands text rules."""
    raw = txt[:txt.find(b"\0")] if b"\0" in txt else txt
    return decode_dl_text(raw.decode("latin-1", errors="replace"))


def itemStr(c, attrs=None):
    """str(struct)."""
    if type(c) is not dict:
        c = vars(c)
    out = ""
    for k, v in c.items():
        if attrs and k not in attrs:
            continue
        out += "%s: " % k
        if type(v) == dict:
            out += "{\n"
            for vk, vv in v.items():
                out += "\t%s: %s\n" % (vk, vv)
            out += "}"
        else:
            out += str(v)
        out += "\n"
    return out


def itemLn(c, attrs=None):
    """Render in line."""
    out = ""
    if not attrs:
        attrs = c.keys()
    for k in attrs:
        l = 5
        if type(k) == tuple:
            k, l = k
        fmt = "%%%ds " % (l)
        out += fmt % (str(c[k])[:l])
    return out
