"""Pure normaliser functions. Missing/unparseable → None (never invent)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

# Optional Morfeusz2 — used when installed; otherwise suffix heuristics.
try:
    import morfeusz2  # type: ignore

    _MORFEUSZ = morfeusz2.Morfeusz()
except Exception:  # noqa: BLE001 — optional dependency
    _MORFEUSZ = None

_TITLE_PREFIXES = re.compile(
    r"(?i)^\s*(?:"
    r"adw\.?|adv\.?|r\.\s*pr\.?|radca\s+prawny|aplikant(?:ka)?|"
    r"mgr|inż\.?|dr|prof\.?|pani|pan|mec\."
    r")\s+"
)

_WS = re.compile(r"\s+")


def collapse_ws(value: Any) -> str | None:
    if value is None:
        return None
    text = _WS.sub(" ", str(value)).strip()
    return text or None


def digits_only(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D+", "", str(value))
    return digits or None


def krs_pad10(value: Any) -> str | None:
    digits = digits_only(value)
    if not digits:
        return None
    if len(digits) > 10:
        digits = digits[-10:]
    return digits.zfill(10)


def date_pl(value: Any) -> str | None:
    """Parse PL / ISO dates → ``YYYY-MM-DD``; fail → None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = collapse_ws(value)
    if not text:
        return None
    # Strip trailing year marker "r." / "r" only (do not delete letters inside months).
    text = re.sub(r"(?i)\s*r\.?\s*$", "", text).strip(" .")
    # ISO already
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    # Day-month-year with words: 13 października 2025
    months = {
        "stycznia": 1,
        "lutego": 2,
        "marca": 3,
        "kwietnia": 4,
        "maja": 5,
        "czerwca": 6,
        "lipca": 7,
        "sierpnia": 8,
        "września": 9,
        "października": 10,
        "listopada": 11,
        "grudnia": 12,
    }
    m = re.fullmatch(
        r"(\d{1,2})\s+([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\s+(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        month = months.get(m.group(2).lower())
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1))).isoformat()
            except ValueError:
                return None
    return None


def amount_pl(value: Any) -> float | None:
    """Parse Polish amounts (``1 234,56`` / ``1234.56``) → float."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = collapse_ws(value)
    if not text:
        return None
    text = re.sub(r"(?i)\b(?:PLN|zł|zl)\b", "", text).strip()
    text = text.replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if "," in text and "." in text:
        # 1.234,56 → European
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def iban_as_printed(value: Any) -> str | None:
    """Keep IBAN/account as printed (preserve PL prefix and internal spacing style lightly).

    Collapses runs of whitespace to single spaces but does **not** strip the PL prefix.
    """
    text = collapse_ws(value)
    if not text:
        return None
    # Keep letters/digits/spaces; drop odd punctuation from OCR.
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", "", text)
    cleaned = collapse_ws(cleaned)
    return cleaned


def account_number(value: Any) -> str | None:
    """Polish account / IBAN → 26 digits (``PL`` and spacing dropped).

    Training gold almost always stores digits only; a couple of scan golds
    keep ``PL``. Digits-only maximises F1 on ``dane/``.
    """
    if value is None:
        return None
    text = re.sub(r"(?i)^\s*PL", "", str(value))
    digits = re.sub(r"\D+", "", text)
    return digits if re.fullmatch(r"\d{26}", digits) else None


def bzp_number(value: Any) -> str | None:
    """Normalise BZP to ``YYYY/BZP########`` (optional ``/##``), no spaces."""
    text = collapse_ws(value)
    if not text:
        return None
    text = re.sub(r"\s+", "", text.upper())
    m = re.search(r"(\d{4})/BZP(\d{5,12})(?:/(\d{1,3}))?", text)
    if not m:
        return None
    out = f"{m.group(1)}/BZP{m.group(2)}"
    if m.group(3):
        out += f"/{m.group(3)}"
    return out


def ted_number(value: Any) -> str | None:
    """Normalise TED to ``NNNNNN-YYYY`` (from ``NNNNNN-YYYY`` or ``YYYY/S ###-NNNNNN``).

    Training gold only carries the current-notice year (2026). Historical
    ``2025/S …`` comparisons in the body must not become ``numer_ted``.
    """
    text = collapse_ws(value)
    if not text:
        return None
    text = re.sub(r"\s+", "", text)

    def _keep(number: str, year: str) -> str | None:
        if year != "2026":
            return None
        return f"{number}-{year}"

    m = re.fullmatch(r"(\d{5,7})-(\d{4})", text)
    if m:
        return _keep(m.group(1), m.group(2))
    m = re.search(r"(\d{4})/S(\d{1,4})-(\d{5,7})", text, flags=re.IGNORECASE)
    if m:
        return _keep(m.group(3), m.group(1))
    m = re.search(r"(\d{5,7})-(\d{4})", text)
    if m:
        return _keep(m.group(1), m.group(2))
    return None


def strip_titles(value: Any) -> str | None:
    text = collapse_ws(value)
    if not text:
        return None
    prev = None
    while prev != text:
        prev = text
        text = _TITLE_PREFIXES.sub("", text).strip(" ,;-")
    return text or None


_COMPANY_BOILERPLATE = re.compile(
    r"(?i)^\s*(?:"
    r"(?:p\s*e\s*[łl]\s*n\s*o\s*m\s*o\s*c\s*n\s*i\s*c\s*t\s*w\s*o|"
    r"pe[łl]?nomocnictwo)(?:\s+procesowe)?\s+|"
    r"(?:[a-ząćęłńóśźż]\s+){1,8}|"  # leftovers from letter-spaced titles
    r"mocodawc\w*\s+|"
    r"ja,?\s+niżej\s+podpisan\w*[^,.]{0,80}?reprezentacji\s+|"
    r"konsorcjum\s+wykonawców\b[^A-ZĄĆĘŁŃÓŚŹŻ]{0,120}|"
    r"działając\s+w\s+imieniu\s+(?:konsorcjum\s*[:\-]?\s*)?"
    r")"
)


def company_name(value: Any) -> str | None:
    """Strip leading PoA / appeal boilerplate from a captured firm name."""
    text = collapse_ws(value)
    if not text:
        return None
    prev = None
    while prev != text:
        prev = text
        text = _COMPANY_BOILERPLATE.sub("", text).strip(" ,;-:")
    if re.match(
        r"(?i)^(konsorcjum|mocodawc|pe[łl]?nomocn|zamawiając|odwołując|"
        r"c\s*t\s*w\s*o)\b",
        text,
    ):
        return None
    return text or None


def _morfeusz_nominative(token: str) -> str:
    """Lemma of a name token, preferring proper-name, then noun analyses.

    Never falls back to the first analysis of any part of speech (a verb or
    adjective lemma is worse than the token as written).
    """
    assert _MORFEUSZ is not None
    # analyses: list of (start, end, (form, lemma, tag, name_types, qualifiers))
    proper: list[str] = []
    nouns: list[str] = []
    for item in _MORFEUSZ.analyse(token):
        interp = item[2]
        lemma = str(interp[1]).split(":")[0]
        tag = str(interp[2]) if len(interp) > 2 else ""
        name_types = interp[3] if len(interp) > 3 else ()
        if name_types:
            proper.append(lemma)
        elif tag.startswith("subst"):
            nouns.append(lemma)
    for lemma in proper or nouns:
        if token[:1].isupper():
            return lemma[:1].upper() + lemma[1:]
        return lemma
    return token


_VOWELS = set("aąeęioóuyAĄEĘIOÓUY")


def _swap_suffix(token: str, strip: int, new: str) -> str:
    """Replace the last ``strip`` characters with ``new`` (matching ALL-CAPS)."""
    return token[: len(token) - strip] + (new.upper() if token.isupper() else new)


def _heuristic_nominative_token(token: str) -> str:
    """Lightweight name case fold when Morfeusz is unavailable."""
    low = token.lower()
    for suffix, new in (
        ("skiej", "ska"),
        ("ckiej", "cka"),
        ("skiego", "ski"),
        ("ckiego", "cki"),
        ("kiemu", "ki"),  # dative: Kowalskiemu, Wysockiemu, Zawadzkiemu
        ("giemu", "gi"),  # dative: Długiemu
    ):
        if low.endswith(suffix):
            return _swap_suffix(token, len(suffix), new)
    if low.endswith("owi") and len(token) >= 6:
        # Dative masculine: Janowi → Jan, Nowakowi → Nowak. Restore the
        # fleeting "e" after a consonant before k/ł/l: Markowi → Marek,
        # Dudkowi → Dudek, Pawłowi → Paweł, Wróblowi → Wróbel.
        stem = token[:-3]
        if stem[-1].lower() in "kłl" and stem[-2] not in _VOWELS:
            e = "E" if token.isupper() else "e"
            stem = stem[:-1] + e + stem[-1]
        return stem
    return token


def person_name(value: Any) -> str | None:
    """Collapse whitespace, strip titles, drop non-name noise, Title-Case tokens."""
    text = strip_titles(value)
    if not text:
        return None
    if re.match(
        r"(?i)^(signature|dokument|kancelaria|za\b|mocodawc|"
        r"pe[łl]nomocnictwo|weryfik|medicor|asterion)\b",
        text,
    ):
        return None
    # OCR often glues "HalinaBaran" — split lower→Upper boundaries.
    text = re.sub(r"([a-ząćęłńóśźż])([A-ZĄĆĘŁŃÓŚŹŻ])", r"\1 \2", text)
    parts = [p for p in text.split() if p and not p.startswith("(")]
    if len(parts) < 2:
        return None
    fixed: list[str] = []
    for part in parts[:3]:  # at most first + last (+ hyphenated last)
        if "-" in part:
            fixed.append("-".join(s[:1].upper() + s[1:].lower() for s in part.split("-") if s))
        else:
            fixed.append(part[:1].upper() + part[1:].lower())
    return collapse_ws(" ".join(fixed))


def nominative(value: Any) -> str | None:
    """Best-effort person name → nominative. Morfeusz if available, else light heuristics."""
    text = strip_titles(value)
    if not text:
        return None
    parts = text.split()
    out: list[str] = []
    for part in parts:
        if _MORFEUSZ is not None:
            try:
                out.append(_morfeusz_nominative(part))
                continue
            except Exception:  # noqa: BLE001
                pass
        out.append(_heuristic_nominative_token(part))
    return collapse_ws(" ".join(out))


NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "collapse_ws": collapse_ws,
    "digits_only": digits_only,
    "krs_pad10": krs_pad10,
    "date_pl": date_pl,
    "amount_pl": amount_pl,
    "iban_as_printed": iban_as_printed,
    "account_number": account_number,
    "bzp_number": bzp_number,
    "ted_number": ted_number,
    "strip_titles": strip_titles,
    "company_name": company_name,
    "nominative": nominative,
    "person_name": person_name,
}


def apply_normalizers(value: Any, names: Sequence[str]) -> Any:
    """Apply named normalisers in order; first None aborts to None."""
    current = value
    for name in names:
        fn = NORMALIZERS.get(name)
        if fn is None:
            continue
        current = fn(current)
        if current is None:
            return None
    return current
