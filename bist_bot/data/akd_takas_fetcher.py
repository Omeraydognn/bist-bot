"""
AKD (Araci Kurum Dagilimi) ve Takas verisi.

Resmi/acik bir API yok; genelde Takasbank raporlari veya Matriks/Foreks
gibi terminaller uzerinden manuel/yari-otomatik alinir. Faz 4'e kadar
"NoAkdFetcher" ile pasif kalir; skorlayici bu durumda ilgili agirligi
otomatik atlar.
"""
from __future__ import annotations

import abc
from typing import Any


class BaseAkdTakasFetcher(abc.ABC):
    @abc.abstractmethod
    def fetch_akd(self, symbol: str) -> list[dict[str, Any]] | None:
        raise NotImplementedError


class NoAkdFetcher(BaseAkdTakasFetcher):
    def fetch_akd(self, symbol: str):
        return None


def get_akd_fetcher(provider: str = "none", **kwargs) -> BaseAkdTakasFetcher:
    providers = {
        "none": NoAkdFetcher,
        # "takasbank": TakasbankFetcher,  # ileride eklenecek
    }
    if provider not in providers:
        raise ValueError(f"Bilinmeyen AKD/takas kaynagi: {provider}")
    return providers[provider](**kwargs)
