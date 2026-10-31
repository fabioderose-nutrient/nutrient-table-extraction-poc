"""Settings from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    web_sdk_license_key: str = env("NUTRIENT_WEB_SDK_LICENSE_KEY")
    vision_base_url: str = env("VISION_BASE_URL", "http://localhost:11434/v1")
    vision_model: str = env("VISION_MODEL", "qwen2.5vl:7b")
    vision_api_key: str = env("VISION_API_KEY")
    vision_timeout: float = float(env("VISION_TIMEOUT", "600"))
    render_dpi: int = int(env("RENDER_DPI", "150"))
    documents: Path = (ROOT / env("DOCUMENTS_FOLDER", "samples/documents")).resolve()
    uploads: Path = (ROOT / env("OUTPUT_FOLDER", "output") / "uploads").resolve()
    output: Path = (ROOT / env("OUTPUT_FOLDER", "output")).resolve()
    ground_truth: Path = ROOT / "samples" / "ground-truth.json"
    host: str = env("HOST", "127.0.0.1")
    port: int = int(env("PORT", "4730"))


settings = Settings()
