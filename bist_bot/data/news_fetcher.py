"""
Haber verisi cekici.

En guvenilir ve resmi kaynak KAP (Kamuyu Aydinlatma Platformu)'dur.
KAP'in "Veri Yayin Servisi" adinda abonelik gerektiren resmi bir REST
API'i var (disclosures, disclosureDetail, downloadAttachment, ... gibi
servisler icerir). Bu proje sablonunda:

  - KAPNewsFetcher: abonelik/API key aldiginda dolduracagin iskelet.
  - DummyNewsFetcher: internet/API olmadan sistemi test edebilmen icin
    sahte veri ureten fetcher (gelistirme asamasinda kullan).

Onemli: KAP web sitesini yetkisiz sekilde otomatik "scrape" etmek
yerine resmi API'ye abone olman veya Matriks/Foreks gibi lisansli
saglayicilarin haber servislerini kullanman onerilir.
"""
from __future__ import annotations

import abc
from datetime import datetime
from typing import Any


class BaseNewsFetcher(abc.ABC):
    @abc.abstractmethod
    def fetch_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """Her biri {published_at, source, title, content, raw_url} olan liste."""
        raise NotImplementedError


class KAPNewsFetcher(BaseNewsFetcher):
    """
    KAP Veri Yayin Servisi REST API entegrasyonu icin iskelet.

    Kullanmak icin:
      1. KAP'a kurumsal abone olup API anahtari/erisim al.
      2. .env dosyana KAP_API_KEY, KAP_API_BASE_URL ekle.
      3. Asagidaki fetch_news metodunu gercek endpoint'lere gore doldur.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url

    def fetch_news(self, symbol: str, limit: int = 20):
        if not self.api_key:
            raise RuntimeError(
                "KAP API anahtari tanimli degil. Once KAP Veri Yayin Servisi'ne "
                "abone olup .env dosyasina KAP_API_KEY eklemen gerekiyor. "
                "Test icin simdilik DummyNewsFetcher kullan."
            )
        # TODO: gercek istek burada yapilacak, ornegin:
        # resp = requests.get(f"{self.base_url}/disclosures",
        #                      params={"symbol": symbol, "limit": limit},
        #                      headers={"Authorization": f"Bearer {self.api_key}"})
        raise NotImplementedError("KAP API entegrasyonu henuz tamamlanmadi.")


class DummyNewsFetcher(BaseNewsFetcher):
    """Gelistirme/test asamasinda internet olmadan calismak icin."""

    def fetch_news(self, symbol: str, limit: int = 20):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return [
            {
                "published_at": now,
                "source": "dummy",
                "title": f"{symbol} icin ornek haber basligi",
                "content": "Bu sahte bir haber. Gercek KAP entegrasyonu eklenene kadar test amaclidir.",
                "raw_url": "",
            }
        ][:limit]


def get_news_fetcher(provider: str = "dummy", **kwargs) -> BaseNewsFetcher:
    providers = {
        "kap": KAPNewsFetcher,
        "dummy": DummyNewsFetcher,
    }
    if provider not in providers:
        raise ValueError(f"Bilinmeyen haber kaynagi: {provider}")
    return providers[provider](**kwargs)
