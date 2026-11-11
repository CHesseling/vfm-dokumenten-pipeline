"""Laedt alle lokalen Modelle fuer den Offline-Betrieb (Image-Build).

Aufruf: python scripts/modelle_laden.py --ziel /models
Layout: <ziel>/hf (HF_HOME: Reranker, GliNER2, Tokenizer), <ziel>/whisper,
<ziel>/docling. Spaetere Tasks ergaenzen hier ihr Modell.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

WHISPER_MODELL = "small"
RERANK_MODELL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
GLINER_MODELL = "fastino/gliner2-base-v1"
# GliNER2 laedt zusaetzlich diesen Tokenizer aus dem Hub.
GLINER_TOKENIZER = "microsoft/mdeberta-v3-base"


def _hf_snapshot(repo: str, **kwargs) -> None:
    from huggingface_hub import snapshot_download

    print(f"==> {repo}", flush=True)
    snapshot_download(repo_id=repo, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ziel", default="/models")
    ziel = Path(parser.parse_args().ziel)
    hf, whisper, docling = ziel / "hf", ziel / "whisper", ziel / "docling"
    for p in (hf, whisper, docling):
        p.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf)

    # Nur safetensors + Tokenizer: das Repo enthaelt zusaetzlich ONNX-,
    # OpenVINO- und pytorch_model.bin-Varianten (rund 3,5 GB Ballast).
    _hf_snapshot(
        RERANK_MODELL,
        allow_patterns=["*.json", "*.model", "*.txt", "model.safetensors"],
    )
    _hf_snapshot(
        GLINER_MODELL,
        allow_patterns=["*.json", "*.model", "*.txt", "model.safetensors"],
    )
    _hf_snapshot(
        GLINER_TOKENIZER,
        allow_patterns=["*.json", "*.model", "*.txt", "spm.model"],
    )

    # faster-whisper legt unter download_root einen HF-Cache an
    from faster_whisper.utils import download_model

    print(f"==> whisper {WHISPER_MODELL}", flush=True)
    download_model(WHISPER_MODELL, cache_dir=str(whisper))

    print("==> docling", flush=True)
    subprocess.run(
        [
            "docling-tools", "models", "download",
            "layout", "tableformer", "easyocr", "-o", str(docling),
        ],
        check=True,
    )
    print("Fertig.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
