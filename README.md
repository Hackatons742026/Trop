# TROP (Odwołania2json)

HackNation pipeline: PDF appeal dossiers → structured JSON.

**Rules-first by default** — no LLM is required (or used) for a normal run.
`config/llm.yaml` sets `default_profile: none` for maximum model-size score.

## Install

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Pinned runtime deps: `requirements.txt` (Python **3.13**, `pypdfium2` PDF backend —
**not** PyMuPDF). Editable package entry point: `trop`.

Quick start scripts:

```bat
start.bat
```

```bash
chmod +x start.sh && ./start.sh
```

## CLI

```bash
# Batch PDF → mirrored same-stem JSON
trop run --input input --output output --workers 2

# Optional evidence sidecars (outside output/; never scored)
trop run --input input --output output --evidence evidence --workers 2

# List YAML document classes
trop classes list

# Scaffold a new class from classes/_template
trop new-class my_class

# Score predictions vs gold (micro-F1); write JSON / Markdown / CSV report
trop eval --pred output --gold data/train/gold --report eval/reports/dev.md
trop eval --pred output --gold data/train/gold --report eval/reports/dev.csv
```

Exit `0` when `--input` exists; per-file errors / OOC write exactly `{}` and continue.

## Official layout (`/opt/solution`)

Judges run from the Azure VM path:

```text
/opt/solution/
  ├── input/      # upload PDFs here
  ├── output/     # collect mirrored JSON here
  ├── evidence/   # optional sidecars (not scored)
  ├── config/     # app.yaml, negatives.yaml, llm.yaml
  ├── classes/    # class.yaml + schema.json per type
  ├── app/        # Streamlit GUI (app/gui.py)
  ├── RUN.md
  ├── Dockerfile
  └── docker-compose.yml
```

Exact judge command and reboot notes: **[RUN.md](RUN.md)**.

```bash
docker compose build trop
docker compose run --rm trop
```

## GUI

`app/gui.py` is a Streamlit side-by-side preview: upload PDFs, run the same
pipeline as `trop run`, inspect and download the JSON. Compose service `gui`
listens on **port 8080** (`restart: unless-stopped`, non-root, no
authentication — restrict the port at the firewall).
Do not put competition assets in `input/` or `output/`.

```bash
docker compose up -d gui
# or locally:
streamlit run app/gui.py --server.port 8080
```

## Behaviour

- Recursively processes `*.pdf` / `*.PDF`
- Mirrors relative paths under `--output`
- JSON name = PDF stem + `.json` (spaces / Polish characters preserved)
- Per-file errors / OOC → write `{}`, log, continue
- OCR only when page text has &lt;40 printable chars or printable ratio &lt;0.9
- Default `workers: 2` (2 vCPU), `dpi: 200`, page caps in `config/app.yaml`
- Classes discovered from `classes/*/class.yaml` (folders starting with `_` ignored)
- Evidence sidecars (off by default; the Docker batch command enables them) go under
  `evidence/<rel>/<stem>.evidence.json` —
  scorers that glob `output/**/*.json` never see them
- `data/` is local / **gitignored** (scratch gold imports)

## Docs

| Doc | Contents |
|-----|----------|
| [RUN.md](RUN.md) | Azure `/opt/solution`, Docker, OCR bake-in |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline stages, stack, class config |
| [docs/ADDING_A_CLASS.md](docs/ADDING_A_CLASS.md) | How to add a document type from YAML |
| [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md) | Mentor assumptions still open |
| [docs/LICENSING.md](docs/LICENSING.md) | AGPL-safe default path (no PyMuPDF) |

## Eval reports (submission attachment)

```bash
trop eval --pred output --gold path/to/gold --report eval/reports/f1.md
```

Attach the generated Markdown/CSV/JSON from `eval/reports/` to the HackNation
form (FAQ optional). Generated files under `eval/reports/` are gitignored;
keep `.gitkeep`.

## OCR models (first run / Docker)

RapidOCR + onnxruntime download ONNX models on first OCR use. The Dockerfile
runs `rapidocr download_models` and warms the engine. Local helper:

```bash
bash tools/bake_ocr_models.sh
```

## Tests

```bat
pip install -r requirements-dev.txt
pytest
```
