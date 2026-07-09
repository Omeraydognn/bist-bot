"""
Karar motoru.

Tum alt analiz modullerinin (teknik, haber, temel, derinlik, akd)
skorlarini config'teki agirliklarla birlestirip tek bir nihai skor ve
AL / SAT / TUT karari uretir.

Onemli tasarim karari: eger bir veri kaynagi henuz aktif degilse
(skor None ise), o kaynagin agirligi otomatik olarak digerlerine
dagitilir (normalize edilir). Boylece Faz 1'de sadece teknik analiz
varken bile sistem tutarli calisir; Faz 4-5'te yeni kaynaklar
eklendiginde formul otomatik uyum saglar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DecisionResult:
    symbol: str
    date: str
    final_score: float
    decision: str
    sub_scores: dict
    weights_used: dict
    details: dict

    def to_storage_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "date": self.date,
            "technical_score": self.sub_scores.get("technical"),
            "news_score": self.sub_scores.get("news_sentiment"),
            "fundamental_score": self.sub_scores.get("fundamental"),
            "depth_score": self.sub_scores.get("depth"),
            "akd_score": self.sub_scores.get("akd_takas"),
            "final_score": self.final_score,
            "decision": self.decision,
            "details": json.dumps(self.details, ensure_ascii=False),
        }


def _normalize_weights(weights: dict, available_keys: list[str]) -> dict:
    """Sadece elde veri olan sinyallerin agirligini kullanip toplami 1'e tamamlar."""
    filtered = {k: v for k, v in weights.items() if k in available_keys}
    total = sum(filtered.values())
    if total == 0:
        # hicbir agirlik yoksa esit dagit
        n = len(available_keys) or 1
        return {k: 1 / n for k in available_keys}
    return {k: v / total for k, v in filtered.items()}


def decide(
    symbol: str,
    technical_result: dict,
    news_result: dict | None,
    fundamental_result: dict | None,
    depth_result: dict | None,
    akd_result: dict | None,
    weights: dict,
    thresholds: dict,
) -> DecisionResult:
    raw_scores = {"technical": technical_result.get("score", 0.0)}
    if news_result is not None:
        raw_scores["news_sentiment"] = news_result.get("score", 0.0)
    if fundamental_result is not None:
        raw_scores["fundamental"] = fundamental_result.get("score", 0.0)
    if depth_result is not None:
        raw_scores["depth"] = depth_result.get("score", 0.0)
    if akd_result is not None:
        raw_scores["akd_takas"] = akd_result.get("score", 0.0)

    used_weights = _normalize_weights(weights, list(raw_scores.keys()))

    final_score = sum(raw_scores[k] * used_weights[k] for k in raw_scores)
    final_score = max(-1.0, min(1.0, final_score))

    buy_th = thresholds.get("buy", 0.3)
    sell_th = thresholds.get("sell", -0.3)

    if final_score >= buy_th:
        decision = "AL"
    elif final_score <= sell_th:
        decision = "SAT"
    else:
        decision = "TUT"

    details = {
        "technical": technical_result.get("details"),
        "news": news_result.get("details") if news_result else None,
        "fundamental": fundamental_result.get("details") if fundamental_result else None,
    }

    return DecisionResult(
        symbol=symbol,
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        final_score=round(final_score, 4),
        decision=decision,
        sub_scores=raw_scores,
        weights_used=used_weights,
        details=details,
    )
