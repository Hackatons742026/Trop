# TROP architecture

Rules-first PDF → schema JSON pipeline for HackNation Odwołania2json.

## Pipeline stages

```text
discover PDFs
    → ingest (pypdfium2 text layer; RapidOCR fallback)
    → classify (YAML keywords + negatives → class_id | other)
    → extract (blocks + regex/label/derived → schema skeleton)
    → normalize (dates ISO, KRS/NIP/PESEL, IBAN as printed, …)
    → optional LLM assist (default: none — payload unchanged)
    → write output/<rel>/<stem>.json
    → optional evidence/<rel>/<stem>.evidence.json
```

| Stage | Package | Notes |
|-------|---------|--------|
| Discover | `trop.io.discover` | Recursive `*.pdf`; same-stem JSON names |
| Ingest | `trop.ingest` | Text layer first; OCR when weak |
| Classify | `trop.classify` | Content-only; never filename |
| Extract | `trop.extract` | Per-class YAML extractors |
| Normalize | `trop.normalize` | Shared hooks from `class.yaml` |
| LLM (optional) | `trop.llm` | Profile `none` by default |
| Write | `trop.io.writer` | Scored JSON only under `output/` |
| Evidence | `trop.io.evidence` | Sidecars **outside** `output/` |
| Orchestrate | `trop.orchestrator` | Per-file isolation; workers |
| Eval | `eval.score` | Micro-F1; hold-out `przyklad_46–60` |

Out-of-class / look-alike / hard failure → exactly `{}` (same stem as the PDF).
Evidence never appears in the scored file.

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python **3.13** (`python:3.13-slim` in Docker) |
| PDF (default) | **pypdfium2** — AGPL-safe default path |
| OCR | RapidOCR + onnxruntime (models baked in image) |
| Models | Pydantic v2 |
| CLI | Typer + Rich |
| Config | PyYAML (`config/app.yaml`, `classes/*/class.yaml`) |
| Fuzzy match | rapidfuzz (eval long-string fields ≥80) |
| HTTP (optional LLM) | httpx |
| GUI (FE) | Streamlit `app/gui.py` on port 8080 |

See [LICENSING.md](LICENSING.md): default lockfile has **no AGPL** runtime
dependency; **PyMuPDF is not used**.

## Class configuration

Classes live under `classes/<id>/`:

```text
classes/
  odwolanie/
    class.yaml      # detect keywords, blocks, fields, lists
    schema.json     # official shape (null for misses)
    dicts/          # optional id→label maps
  _template/              # ignored (name starts with _)
  _demo_przystapienie/    # docs-only demo; ignored like _template
```

Discovery: any `classes/*/class.yaml` whose folder does **not** start with `_`.
Official defaults: `odwolanie`, `pelnomocnictwo`, `przelew`.
Adding a type does not require a Python change — see [ADDING_A_CLASS.md](ADDING_A_CLASS.md).

Negatives / look-alikes: `config/negatives.yaml` (content veto → `{}`).

## I/O contract

- **Input:** recursive PDFs under `--input` (Azure: `/opt/solution/input`).
- **Output:** mirrored tree under `--output`; name = PDF stem + `.json`.
- **Evidence (optional, off by default):** only when CLI `--evidence DIR` or
  env/`paths.evidence_dir` is explicitly set (config default is `null`) →
  `evidence/<rel>/<stem>.evidence.json` with
  `page` / `quote` / `bbox` / `method` / `confidence` per field.
- Scorers that glob `output/**/*.json` never see evidence sidecars.
- Classified payloads are JSON Schema–validated before write; invalid → `{}`.

## LLM (optional, off by default)

`config/llm.yaml`:

```yaml
default_profile: none
```

Enabled profiles use an OpenAI-compatible HTTP API (`trop.llm`). Missing key or
failed call leaves the rules-only JSON intact. Keys live only in
`/opt/solution/.env` (see `.env.example`), never in git.

## Evaluation

```bash
trop eval --pred output --gold <gold> --report eval/reports/dev.md
```

`--report` suffix selects format: `.json`, `.md`, `.csv`. Attach generated
tables from `eval/reports/` to the submission form when desired.

## Open mentor questions

Assumptions that are still open (PESEL type, partial redaction → null, etc.)
are listed in [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) so we do not invent answers.
