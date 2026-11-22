# TROP — runbook (Azure VM + Docker)

## Azure VM layout

Judge / demo VM path convention:

```text
/opt/solution/
  ├── .env                 # secrets + overrides (from .env.example; never commit)
  ├── config/              # app.yaml, negatives.yaml
  ├── classes/             # class.yaml + schema.json per document type
  ├── input/               # drop PDFs here (empty in git; no assets checked in)
  ├── output/              # mirrored same-stem JSON (empty in git)
  ├── evidence/            # optional debug dumps
  ├── app/                 # Streamlit GUI (app/gui.py)
  ├── src/trop/            # package (editable install)
  ├── Dockerfile
  ├── docker-compose.yml
  └── …
```

- Keep **no competition assets** inside `input/` or `output/` in the repo.
- `data/` stays local / gitignored for scratch gold imports.
- After VM reboot, re-run the batch (containers do not auto-process the case folder).

## Exact judge command

From `/opt/solution` (or the cloned repo root):

```bash
docker compose run --rm trop
```

Equivalent local (no Docker):

```bash
trop run --input input --output output --evidence evidence --workers 2
```

Exit `0` when `--input` exists; per-file failures write `{}` and continue.

## Build image (OCR models baked)

```bash
docker compose build trop
```

The Dockerfile:

1. Installs pinned `requirements.txt` (Python 3.13, pypdfium2 — **no PyMuPDF**).
2. Runs `rapidocr download_models`.
3. Warms `RapidOCR()` once so cold starts stay offline.

Offline / rebuild helper on a networked machine:

```bash
bash tools/bake_ocr_models.sh
```

## Compose services

| Service | Role | Ports |
|---------|------|-------|
| `trop`  | One-shot batch PDF → JSON | — |
| `gui`   | Streamlit GUI on 8080 (`restart: unless-stopped`, non-root, no auth) | `8080` |

Batch only:

```bash
docker compose run --rm trop
```

GUI (restrict port 8080 at the VM firewall / NSG — it has no authentication):

```bash
docker compose up -d gui
```

## Performance defaults (2 vCPU)

| Setting | Default | Notes |
|---------|---------|-------|
| `workers` | `2` | One worker per vCPU on the 2-core judge VM |
| `dpi` | `200` | Render DPI for OCR pages |
| `max_dpi` | `250` | Hard cap — CLI/env cannot exceed |
| `max_pages` | `40` | Pages read per PDF |
| OCR | only when text weak | `<40` printable chars or printable ratio `<0.9` |
| `ocr.max_pages` | `20` | Cap OCR pages even if more pages are weak |
| PDFium lock | process-wide | PDFium is not thread-safe; all pypdfium2 calls serialized |
| OCR lock | process-wide | RapidOCR inference serialized |
| Compose `user` (`trop`) | `0:0` | Root by default so mounted `./output` is writable |
| Compose `user` (`gui`) | `1000:1000` | Non-root; read-only mounts of `classes/`, `config/`, `app/` |

Tune via `config/app.yaml` or `TROP_*` env (see `.env.example`).

## Environment

```bash
cp .env.example .env
# set TROP_LLM__API_KEY if/when an LLM profile is enabled in config/llm.yaml
```

## Evidence sidecars

Optional and **off by default** (`paths.evidence_dir: null`). Written **outside**
`output/` only when you pass `--evidence` or set `TROP_EVIDENCE_DIR`:

```bash
trop run --input input --output output --evidence evidence --workers 2
```

Files land at `evidence/<rel>/<stem>.evidence.json` (`page` / `quote` / `bbox` /
`method` / `confidence`). Scorers that glob `output/**/*.json` never see them.
Docker Compose batch command passes `--evidence` explicitly for the judge path.

## Eval report for submission

```bash
trop eval --pred output --gold path/to/gold --report eval/reports/f1.md
# or: --report eval/reports/f1.csv
```

Attach the generated table from `eval/reports/` to the HackNation form when needed.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/LICENSING.md](docs/LICENSING.md).