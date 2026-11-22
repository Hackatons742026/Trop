"""Map free-text zarzut phrases → czynnosc_powod_id (1–12)."""

from __future__ import annotations

import re
import unicodedata

from trop.registry.loader import load_czynnosc_powod_dict

# Longer / more specific phrases first.
_PHRASE_TO_ID: tuple[tuple[str, int], ...] = (
    (r"zaniechanie\s+unieważnienia\s+postępowania", 10),
    (r"decyzj\w*\s+o\s+unieważnieniu\s+postępowania", 9),
    (r"unieważnieni\w*\s+postępowania", 9),
    # Narrative filings: "Zamawiający … unieważnił postępowanie" (incl. OCR typos).
    (r"unieważni\w*\s+postępowanie", 9),
    (r"zaniechanie\s+wykluczenia\s+wykonawcy", 8),
    (r"zaniechanie\s+odrzucenia\s+oferty", 7),
    (r"odpowiedzi/?wyjaśnienia\s+do\s+SWZ", 6),
    (r"wyjaśnieni\w*\s+do\s+SWZ", 6),
    (r"odpowiedzi\s+do\s+SWZ", 6),
    (r"modyfikacj\w*\s+treści\s+SWZ", 5),
    (r"publikacj\w*\s+specyfikacji\s+warunków\s+zamówienia", 4),
    (r"specyfikacj\w*\s+warunków\s+zamówienia", 4),
    # Do not map bare "SWZ" → id 4; require longer phrases above.
    (r"projektowane\s+postanowienia\s+umowy", 12),
    (r"ogłoszeni\w*\s+wyboru\s+oferty", 2),
    (r"decyzj\w*\s+o\s+wykluczeniu\s+wykonawcy", 3),
    (r"wykluczy\w*\s+wykonawc", 3),
    (r"wykluczeni\w*\s+wykonawcy", 3),
    (r"decyzj\w*\s+o\s+odrzuceniu\s+oferty", 1),
    (r"odrzuci\w*\s+ofert", 1),
    (r"odrzuceni\w*\s+oferty", 1),
    # OPZ last: appeals often mention it in later zarzuty without it being the act.
    (r"opis\s+przedmiotu\s+zamówienia", 11),
    (r"\bOPZ\b", 11),
)


def _fold(text: str) -> str:
    # Keep Polish diacritics — patterns use them; only lowercase.
    return text.casefold()


def map_text_to_powod_id(text: str | None) -> int | None:
    if not text:
        return None
    folded = _fold(text)
    for pattern, pid in _PHRASE_TO_ID:
        if re.search(pattern, folded, flags=re.IGNORECASE):
            return pid
    # Exact opis match against dict
    mapping = load_czynnosc_powod_dict()
    collapsed = unicodedata.normalize("NFC", " ".join(text.split()))
    for pid, opis in mapping.items():
        if collapsed.casefold() == opis.casefold():
            return int(pid)
    return None


def opis_for_id(powod_id: int | None) -> str | None:
    if powod_id is None:
        return None
    mapping = load_czynnosc_powod_dict()
    return mapping.get(int(powod_id))
