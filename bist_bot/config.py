"""
Merkezi konfigurasyon yukleyici.
Tum modul bu dosya uzerinden ayni config nesnesine erisir,
boylece yeni hisse eklemek settings.yaml disinda hicbir yeri
degistirmeyi gerektirmez.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


@dataclass
class TickerConfig:
    symbol: str
    yahoo_symbol: str
    name: str
    sector: str = ""
    enabled: bool = True


@dataclass
class AppConfig:
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tickers(self) -> list[TickerConfig]:
        return [
            TickerConfig(**t)
            for t in self.raw.get("tickers", [])
            if t.get("enabled", True)
        ]

    def get_ticker(self, symbol: str) -> TickerConfig | None:
        for t in self.tickers:
            if t.symbol.upper() == symbol.upper():
                return t
        return None

    @property
    def data_sources(self) -> dict:
        return self.raw.get("data_sources", {})

    @property
    def scoring_weights(self) -> dict:
        return self.raw.get("scoring_weights", {})

    @property
    def decision_thresholds(self) -> dict:
        return self.raw.get("decision_thresholds", {})

    @property
    def storage(self) -> dict:
        return self.raw.get("storage", {})

    @property
    def risk(self) -> dict:
        return self.raw.get("risk", {})

    @property
    def ai(self) -> dict:
        return self.raw.get("ai", {})

    @property
    def db_path(self) -> Path:
        rel_path = self.storage.get("path", "data_store/bist_bot.db")
        p = PROJECT_ROOT / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return AppConfig(raw=raw)


# Kolay erisim icin tekil (singleton) config nesnesi
_config_instance: AppConfig | None = None


def get_config() -> AppConfig:
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance
