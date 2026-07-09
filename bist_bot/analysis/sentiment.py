"""
Haber sentiment analiz modulu.

Baslangicta basit bir anahtar-kelime tabanli skorlayici sunuyoruz
(harici API/gpu gerektirmez, hemen calisir). Ileride bunun yerine
gercek bir NLP/LLM tabanli sentiment modeli (ör. Anthropic API ile
haberi analiz ettirmek) takilabilir - arayuz ayni kalacak sekilde
tasarlandi.
"""
from __future__ import annotations

import abc

POSITIVE_WORDS = [
    "rekor", "artis", "yukseldi", "buyume", "kar", "anlasma", "ihracat",
    "yeni siparis", "sozlesme", "onay", "basari", "genisleme", "temettü",
    "temettu", "guclu",
]
NEGATIVE_WORDS = [
    "dusus", "zarar", "kayip", "iptal", "sorusturma", "ceza", "dava",
    "gerileme", "kriz", "iflas", "gecikme", "risk", "olumsuz", "azalis",
]


class BaseSentimentAnalyzer(abc.ABC):
    @abc.abstractmethod
    def score_text(self, text: str) -> float:
        """-1 (cok olumsuz) ile +1 (cok olumlu) arasi skor."""
        raise NotImplementedError


class KeywordSentimentAnalyzer(BaseSentimentAnalyzer):
    def score_text(self, text: str) -> float:
        if not text:
            return 0.0
        t = text.lower()
        pos = sum(t.count(w) for w in POSITIVE_WORDS)
        neg = sum(t.count(w) for w in NEGATIVE_WORDS)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total


def analyze_news(news_items: list[dict], analyzer: BaseSentimentAnalyzer | None = None) -> dict:
    """
    news_items: storage.get_recent_news formatinda liste (title, content icerir)
    Cikti: {"score": float, "reason": str, "details": {...}}
    """
    analyzer = analyzer or KeywordSentimentAnalyzer()

    if not news_items:
        return {"score": 0.0, "reason": "Haber bulunamadi", "details": {}}

    scored = []
    for item in news_items:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        s = analyzer.score_text(text)
        scored.append({"title": item.get("title"), "score": round(s, 3)})

    avg_score = sum(x["score"] for x in scored) / len(scored)

    return {
        "score": float(avg_score),
        "reason": f"{len(news_items)} haberin ortalama sentiment skoru",
        "details": {"items": scored},
    }
