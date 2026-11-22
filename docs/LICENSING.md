# Licensing / AGPL check

## Default submission path — no AGPL

The **default** runtime stack pinned in `requirements.txt` / `pyproject.toml` is
chosen for UZP handover friendliness:

| Dependency | Role | Note |
|------------|------|------|
| **pypdfium2** | Default PDF backend | Not AGPL; preferred over PyMuPDF |
| rapidocr + onnxruntime | OCR | Permissive / as declared upstream |
| pydantic, typer, rich, pyyaml, httpx, … | App stack | Permissive |

**PyMuPDF is not used** on the default path (not in requirements, not imported).
If a non-default PDF backend were ever added, it must sit behind an explicit
opt-in flag and must not be the judge/Docker default.

## What we checked

- Locked / pinned deps in `requirements.txt` for the image build.
- `trop.ingest.pdf_backend` documents pypdfium2 as the only default backend.
- Dockerfile installs the same pinned set (no alternate PDF wheel).

## Operator note

Optional LLM keys (if a non-`none` profile is enabled) live only in
`/opt/solution/.env` — never in git. LLM is **off** by default
(`config/llm.yaml` → `default_profile: none`).
