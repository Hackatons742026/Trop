"""Value normalisers used by extractors."""

from trop.normalize.fns import (
    NORMALIZERS,
    amount_pl,
    apply_normalizers,
    bzp_number,
    collapse_ws,
    date_pl,
    digits_only,
    iban_as_printed,
    krs_pad10,
    nominative,
    strip_titles,
    ted_number,
)

__all__ = [
    "NORMALIZERS",
    "amount_pl",
    "apply_normalizers",
    "bzp_number",
    "collapse_ws",
    "date_pl",
    "digits_only",
    "iban_as_printed",
    "krs_pad10",
    "nominative",
    "strip_titles",
    "ted_number",
]
