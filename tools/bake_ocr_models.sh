#!/usr/bin/env bash
# Bake / warm RapidOCR ONNX models (run during Docker build or offline prep).
# Models land under the rapidocr package ``models/`` directory by default.
set -euo pipefail

echo "[bake_ocr] downloading RapidOCR models…"
rapidocr download_models

echo "[bake_ocr] warming engine (loads ONNX)…"
python - <<'PY'
from trop.ingest.ocr import get_ocr_engine

get_ocr_engine()
print("[bake_ocr] OK")
PY
