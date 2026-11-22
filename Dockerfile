# TROP batch image — layout matches Azure VM /opt/solution.
# Host mounts: input/, output/, evidence/, classes/, config/
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TROP_CONFIG=/opt/solution/config/app.yaml \
    HOME=/home/trop

# OpenCV headless / onnxruntime runtime libs
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 trop

WORKDIR /opt/solution

# Dependency layer (editable install needs pyproject + src)
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -r requirements.txt \
    && rapidocr download_models \
    && python -c "from trop.ingest.ocr import get_ocr_engine; get_ocr_engine(); print('OCR models warmed')"

# App tree: classes, config, tools, app stub, docs
COPY classes ./classes
COPY config ./config
COPY eval ./eval
COPY tools ./tools
COPY app ./app
COPY docs ./docs
COPY RUN.md .env.example ./

RUN mkdir -p /opt/solution/input /opt/solution/output /opt/solution/evidence \
    && chown -R trop:trop /opt/solution /home/trop

# Default image user is non-root. docker-compose overrides to root (0:0) for the
# batch `trop` service so bind-mounted ./output and ./evidence stay writable on
# Azure (host uid mismatch). Override with TROP_UID/TROP_GID if needed.
USER trop

# Official one-shot batch (compose overrides user + volumes):
#   docker compose run --rm trop
CMD ["trop", "run", "--input", "/opt/solution/input", "--output", "/opt/solution/output", "--evidence", "/opt/solution/evidence", "--workers", "2"]
