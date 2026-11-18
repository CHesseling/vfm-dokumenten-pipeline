# Stufe 1: Modelle laden (nur Downloads, laeuft auf der Build-Plattform,
# nie unter QEMU). Modellpfade sind plattformunabhaengig.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS modelle
ENV PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/mvenv && pip install uv
ENV PATH="/opt/mvenv/bin:$PATH"
# Versionen kommen aus uv.lock (als pip-Constraints), damit die Modell-Artefakte
# zur Laufzeit-Version passen: docling-tools, faster-whisper usw. sind exakt
# die gelockten Versionen, auch transitive Pakete.
COPY pyproject.toml uv.lock /lock/
RUN cd /lock && uv export --frozen --no-dev --no-hashes --no-emit-project 2>/dev/null \
      | grep -v '^ *-' | grep -v '^ *#' > /constraints.txt \
 && pip install -c /constraints.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      torch torchvision huggingface_hub docling easyocr faster-whisper av
WORKDIR /build
COPY scripts/modelle_laden.py .
RUN python modelle_laden.py --ziel /models

# Stufe 2: Python-Abhaengigkeiten + vfm-Konsolenskript
FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen
COPY app ./app
COPY README.md ./
RUN uv sync --no-dev --frozen

# Stufe 3: Laufzeit
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/CHesseling/vfm-dokumenten-pipeline"
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
# UID/GID kommen aus compose (build.args, APP_UID/APP_GID aus .env), damit das
# beim ersten Start angelegte Volume /data zum Container-User passt.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid ${APP_GID} appuser \
 && useradd --create-home --uid ${APP_UID} --gid ${APP_GID} appuser \
 && mkdir -p /data/dateien /material \
 && chown -R ${APP_UID}:${APP_GID} /data /material
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=modelle /models /models
COPY --chown=${APP_UID}:${APP_GID} . .
ENV PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/models/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
# Sicherheitsnetz: CRLF aus einem Windows-Checkout wuerde das Shebang brechen
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh
USER appuser
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
