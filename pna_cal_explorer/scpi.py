from __future__ import annotations

import math
from typing import Iterable
import numpy as np


def quote_scpi(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _strip_one_outer_quote_pair(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1].strip()
    return text


def parse_pna_catalog(text: str | None) -> list[str]:
    if text is None:
        return []
    s = _strip_one_outer_quote_pair(str(text))
    if not s:
        return []

    result: list[str] = []
    buf: list[str] = []
    paren_depth = 0
    quote_char: str | None = None
    i = 0

    while i < len(s):
        ch = s[i]
        if quote_char is not None:
            if ch == quote_char:
                if i + 1 < len(s) and s[i + 1] == quote_char:
                    buf.append(ch)
                    i += 2
                    continue
                quote_char = None
            else:
                buf.append(ch)
            i += 1
            continue

        if ch in ('"', "'"):
            quote_char = ch
        elif ch == '(':
            paren_depth += 1
            buf.append(ch)
        elif ch == ')':
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
        elif ch == ',' and paren_depth == 0:
            item = ''.join(buf).strip().strip('"').strip("'").strip()
            if item:
                result.append(item)
            buf = []
        else:
            buf.append(ch)
        i += 1

    item = ''.join(buf).strip().strip('"').strip("'").strip()
    if item:
        result.append(item)
    return result


def parse_csv_strings(text: str | None) -> list[str]:
    return parse_pna_catalog(text)


def interleaved_to_complex(values: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return np.array([], dtype=np.complex128)
    if arr.size % 2:
        raise ValueError(f"Expected real/imag pairs, got {arr.size} scalar values")
    return arr[0::2] + 1j * arr[1::2]


def format_frequency(freq_hz: float | None) -> str:
    if freq_hz is None or not math.isfinite(freq_hz):
        return ""
    a = abs(freq_hz)
    if a >= 1e9:
        return f"{freq_hz / 1e9:.9g} GHz"
    if a >= 1e6:
        return f"{freq_hz / 1e6:.9g} MHz"
    if a >= 1e3:
        return f"{freq_hz / 1e3:.9g} kHz"
    return f"{freq_hz:.9g} Hz"
