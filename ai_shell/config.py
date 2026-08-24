"""Configuration for the AI shell.

API key resolution order:
1. MOONSHOT_API_KEY environment variable
2. ~/.chameleon_ai/config.toml  (api_key = "sk-...")

The config file can also override base_url and model.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import tomllib

CONFIG_DIR = Path.home() / ".chameleon_ai"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DICT_DIR = CONFIG_DIR / "dicts"

DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_MODEL = "kimi-k2-0905-preview"


@dataclass
class Config:
    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


def load_config() -> Config:
    cfg = Config()
    if CONFIG_FILE.is_file():
        try:
            data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as e:
            print(f"Warning: could not parse {CONFIG_FILE}: {e}")
            data = {}
        cfg.api_key = data.get("api_key") or None
        cfg.base_url = data.get("base_url", DEFAULT_BASE_URL)
        cfg.model = data.get("model", DEFAULT_MODEL)
    env_key = os.environ.get("MOONSHOT_API_KEY")
    if env_key:
        cfg.api_key = env_key
    return cfg


def ensure_dirs() -> None:
    DICT_DIR.mkdir(parents=True, exist_ok=True)
