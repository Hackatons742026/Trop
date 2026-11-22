"""Value normalisers used by extractors."""

from trop.normalize.fns import (
    NORMALIZERS,
    account_number,
    amount_pl,
    apply_normalizers,
    bzp_number,
    collapse_ws,
    company_name,
    date_pl,
    digits_only,
    iban_as_printed,
    krs_pad10,
    nominative,
    person_name,
    place_name,
    strip_titles,
    ted_number,
)

__all__ = [
    "NORMALIZERS",
    "account_number",
    "amount_pl",
    "apply_normalizers",
    "bzp_number",
    "collapse_ws",
    "company_name",
    "date_pl",
    "digits_only",
    "iban_as_printed",
    "krs_pad10",
    "nominative",
    "person_name",
    "place_name",
    "strip_titles",
    "ted_number",
]
