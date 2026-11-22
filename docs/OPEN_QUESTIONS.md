# Open mentor questions / explicit assumptions

Until mentors answer, TROP does **not invent** policy. Each item below is an
explicit assumption wired into the current rules. When an official answer
arrives, update code + this file in the same change.

| Topic | Current assumption | Why it matters |
|-------|--------------------|----------------|
| **PESEL type** | Keep PESEL as a **string** (leading zeros / redaction). | Number type would drop zeros; schema may allow either. |
| **Partial redaction** | Partly redacted names / IDs → **`null`** (do not invent). | Invented values on empty gold are pure FP. |
| **Multiple attorneys** | Prefer list extractors (`pelnomocnicy` / nested `pelnomocnik`); align lists by content in F1. | FAQ list-alignment rule. |
| **TED / BZP suffixes** | Keep numbers **as printed** (including suffixes) unless a normaliser is declared. | Over-stripping creates FP/FN. |
| **80% similarity** | Eval uses `rapidfuzz.fuzz.token_set_ratio >= 80` on named long-string fields only. | Mentor F1 long-string rule; exact algo may be refined. |
| **czynnosc_opis** | Copied **1:1** from the official dictionary (incl. `/` and code 12). | Exact gold match. |
| **IBAN / accounts** | Keep `PL` prefix when present; do not invent country codes. | Official quirk. |
| **Person names** | Prefer nominative forms when a normaliser exists; else leave as written. | Mentors may clarify edge cases. |
| **Company names** | As written in the document — **not** from CEIDG. | Mentors forbade inventing registry names. |
| **LLM** | Default profile **`none`**; assist never required for a scoring run. | Model-size points + handover. |

See also [ARCHITECTURE.md](ARCHITECTURE.md) and [LICENSING.md](LICENSING.md).
