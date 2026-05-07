from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

APP_NAME = "sarathi"
DEFAULTS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "defaults.toml"


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})

    def resolve_path(self, p: str | Path) -> Path:
        p = Path(p)
        if p.is_absolute():
            return p
        return Path(user_data_dir(APP_NAME)) / p


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else Path(os.environ.get("SARATHI_CONFIG", DEFAULTS_PATH))
    with cfg_path.open("rb") as f:
        return Config(raw=tomllib.load(f))
