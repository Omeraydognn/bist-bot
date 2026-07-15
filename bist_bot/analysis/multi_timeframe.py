"""
Coklu Zaman Dilimi (Multi-Timeframe / MTF) analiz motoru.

Mantik: "Buyuk resim yonu soyler, kucuk resim zamanlamayi soyler."

  * GUNLUK  -> ana trend (nehrin akis yonu)
  * 1 SAAT  -> gun ici ana yon
  * 30 DK   -> ara teyit
  * 15 DK   -> giris zamanlamasi (tetik)

Kurallar:
  1. Tum katmanlar ayni yonu gosteriyorsa -> guclu sinyal (yuksek guven)
  2. Ust katmanlar yukari, 15dk asiri satim gosteriyorsa -> "dipten alim
     firsati" (trend yonunde geri cekilme alimi) - scalping icin en
     degerli kurgu budur
  3. Katmanlar celisiyorsa -> guven duser; buyuk celiskide BEKLE
  4. Kullanicinin istedigi gibi kucuk firsatlar da raporlanir: sinyal
     esigine ulasmasa bile her katmanin ne dedigi ciktida gorunur,
     "firsat_notu" alaninda kucuk ama gercek kenarlar isaretlenir.

Veri girisi: {"15m": [...], "30m": [...], "1h": [...], "1d": [...]}
Her deger, standart OHLCV satir listesidir. Eksik katman olabilir -
motor eldekiyle calisir ve hangi katmanin eksik oldugunu soyler.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bist_bot.analysis import technical
from bist_bot.analysis.scalping import analyze_scalp, CostModel, ScalpSignal
from bist_bot.market.session import get_session_state, SessionState

# Katman agirliklari: zamanlama katmanlari daha agir cunku scalping yapiyoruz,
# ama gunluk trend veto gucune sahip (asagida trend_veto mantigi)
TIMEFRAME_WEIGHTS = {
    "15m": 0.40,
    "5m": 0.60,
}


@dataclass
class MTFResult:
    action: str                    # AL / SAT / BEKLE
    confidence: float              # 0..1
    combined_score: float          # -1..+1
    per_timeframe: dict = field(default_factory=dict)
    scalp_signal: ScalpSignal | None = None
    session: SessionState | None = None
    firsat_notu: str = ""          # esik alti kucuk firsatlar dahil aciklama
    reason: str = ""


def analyze_mtf(
    frames: dict[str, list[dict]],
    cost_model: CostModel | None = None,
    min_net_edge_pct: float = 0.20,      # komisyonsuz oldugumuz icin esik dusuruldu
    check_session: bool = True,
    buy_threshold: float = 0.25,
    sell_threshold: float = -0.25,
) -> MTFResult:
    import numpy as np
    from datetime import datetime
    import pytz
    
    tz = pytz.timezone('Europe/Istanbul')
    now = datetime.now(tz).time()
    
    # Morning Gap Filtresi (10:00 - 10:15)
    t_10_00 = datetime.strptime("10:00", "%H:%M").time()
    t_10_15 = datetime.strptime("10:15", "%H:%M").time()
    is_morning_gap = t_10_00 <= now <= t_10_15
    cost_model = cost_model or CostModel()
    session = get_session_state() if check_session else None

    per_tf: dict[str, dict] = {}
    weighted_sum = 0.0
    weight_used = 0.0

    for tf, weight in TIMEFRAME_WEIGHTS.items():
        rows = frames.get(tf)
        if not rows or len(rows) < 30:
            per_tf[tf] = {"score": None, "note": "veri yok/yetersiz"}
            continue
        res = technical.analyze(rows)
        
        if is_morning_gap:
            sub = res.get("details", {}).get("sub_scores", {})
            valid_subs = {k: v for k, v in sub.items() if k not in ["rsi", "bollinger"]}
            if valid_subs:
                adjusted_score = float(np.clip(sum(valid_subs.values()) / len(valid_subs), -1, 1))
                res["score"] = adjusted_score
        
        per_tf[tf] = {
            "score": round(res["score"], 3),
            "rsi": res["details"].get("rsi"),
            "sub": res["details"].get("sub_scores"),
        }
        weighted_sum += res["score"] * weight
        weight_used += weight

    # Bilgi katmanlari (agirliksiz): 1h ara teyit ve 1d ana trend.
    # Skora dahil edilmez ama gunluk trend vetosu ve rapor icin kullanilir.
    for info_tf in ("1h", "1d"):
        if info_tf in per_tf:
            continue
        rows = frames.get(info_tf)
        if rows and len(rows) >= 30:
            res = technical.analyze(rows)
            per_tf[info_tf] = {
                "score": round(res["score"], 3),
                "rsi": res["details"].get("rsi"),
                "not": "bilgi katmani (skora dahil degil, trend filtresi)",
            }

    if weight_used == 0:
        return MTFResult(
            action="BEKLE", confidence=0, combined_score=0,
            per_timeframe=per_tf, session=session,
            reason="Hicbir zaman diliminde yeterli veri yok.",
        )

    combined = weighted_sum / weight_used  # eksik katmanlar otomatik normalize

    # 5dk veya 15dk katmaninda scalp firsati var mi? (giris tetigi)
    scalp = None
    trigger_frame = frames.get("5m") or frames.get("15m")
    if trigger_frame and len(trigger_frame) >= 25:
        scalp = analyze_scalp(trigger_frame, cost_model=cost_model, min_net_edge_pct=min_net_edge_pct)

    # ---- TREND VETOSU: gunluk trend guclu sekilde tersse, scalp sinyali kisitla
    daily_score = per_tf.get("1d", {}).get("score")
    trend_veto = ""
    if scalp and scalp.action == "AL" and daily_score is not None and daily_score < -0.4:
        trend_veto = "Gunluk trend guclu negatif -> 15dk AL sinyali veto edildi (nehre karsi yuzme)."
        scalp_action = "BEKLE"
    elif scalp and scalp.action == "SAT" and daily_score is not None and daily_score > 0.4:
        trend_veto = "Gunluk trend guclu pozitif -> 15dk SAT sinyali veto edildi."
        scalp_action = "BEKLE"
    else:
        scalp_action = scalp.action if scalp else "BEKLE"

    # ---- Nihai karar mantigi
    # Scalp tetigi + MTF uyumu birlikte degerlendirilir
    if scalp_action == "AL" and combined >= 0:
        action = "AL"
        confidence = min(0.5 + combined * 0.5 + (scalp.confidence if scalp else 0) * 0.3, 0.95)
    elif scalp_action == "SAT" and combined <= 0:
        action = "SAT"
        confidence = min(0.5 + abs(combined) * 0.5 + (scalp.confidence if scalp else 0) * 0.3, 0.95)
    elif combined >= buy_threshold:
        action = "AL"
        confidence = min(0.4 + combined * 0.5, 0.85)
    elif combined <= sell_threshold:
        action = "SAT"
        confidence = min(0.4 + abs(combined) * 0.5, 0.85)
    else:
        action = "BEKLE"
        confidence = 0.0

    # ---- Seans kontrolu (kullanicinin istedigi 10:00-18:00 bilinci)
    session_note = ""
    if session:
        if not session.is_open:
            session_note = f"[SEANS] {session.note}"
            # Piyasa kapaliyken sinyal "bilgi" olarak kalir, aksiyon onerilmez
        elif not session.can_open_position and action in ("AL", "SAT"):
            session_note = f"[SEANS] {session.note} -> sinyal var ama su an yeni pozisyon onerilmez."
            action = "BEKLE"
        elif session.should_close_positions:
            session_note = f"[SEANS] {session.note}"

    # ---- Kucuk firsat notu: esik alti ama gercek kenarlar da raporlanir
    firsat_parts = []
    for tf, info in per_tf.items():
        s = info.get("score")
        if s is not None and abs(s) >= 0.15:
            yon = "yukari" if s > 0 else "asagi"
            firsat_parts.append(f"{tf}: {yon} egilim ({s:+.2f})")
    if scalp and scalp.action == "BEKLE" and scalp.expected_move_pct > 0:
        firsat_parts.append(f"15dk tipik oynama: %{scalp.expected_move_pct}")
    firsat_notu = " | ".join(firsat_parts) if firsat_parts else "Belirgin kucuk firsat da yok."

    reason_parts = [f"MTF birlesik skor: {combined:+.3f} (agirlikli, eksik katman normalize)."]
    if scalp:
        reason_parts.append(f"15dk tetik: {scalp.action} ({scalp.reason})")
    if trend_veto:
        reason_parts.append(trend_veto)
    if session_note:
        reason_parts.append(session_note)

    return MTFResult(
        action=action,
        confidence=round(confidence, 2),
        combined_score=round(combined, 3),
        per_timeframe=per_tf,
        scalp_signal=scalp,
        session=session,
        firsat_notu=firsat_notu,
        reason=" ".join(reason_parts),
    )
