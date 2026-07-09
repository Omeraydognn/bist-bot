"""
BIST Pay Piyasasi seans takvimi ve zaman bilinci.

Botun "saatin kac oldugunu bilmesi" kritik, cunku:
  * Piyasa 10:00 - 18:00 arasi acik (surekli islem ~10:00-18:00,
    oncesinde acilis muzayedesi, sonunda kapanis muzayedesi var)
  * Acilistan hemen sonraki dakikalar (gap + yuksek volatilite) ve
    kapanisa yakin dakikalar (kapanis muzayedesi etkisi) scalping
    icin en riskli zamanlardir
  * Gun sonunda acik pozisyon tasimak = gece boyu habere/gap'e acik
    kalmak demektir. Gunluk kazanc hedefli bir scalper genelde
    kapanistan once pozisyon kapatir (bu davranis config'ten acilir/kapanir)

NOT: Resmi tatiller ve yarim gunler icin basit bir liste tutulur;
gercek kullanimda Borsa Istanbul'un resmi tatil takvimiyle
guncellenmelidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


# BIST Pay Piyasasi ana seans (surekli islem) saatleri
MARKET_OPEN = time(10, 0)
MARKET_CLOSE = time(18, 0)

# Riskli pencereler (dakika)
AVOID_AFTER_OPEN_MIN = 15    # acilistan sonra ilk 15 dk yeni pozisyon acma
AVOID_BEFORE_CLOSE_MIN = 20  # kapanisa 20 dk kala yeni pozisyon acma
FORCE_CLOSE_BEFORE_MIN = 10  # kapanisa 10 dk kala acik pozisyonu kapat (gun-ici mod)

# Hafta sonu gunleri (Pazartesi=0 ... Pazar=6)
WEEKEND_DAYS = (5, 6)


@dataclass
class SessionState:
    is_open: bool
    phase: str            # "kapali", "acilis_riskli", "normal", "kapanis_yakin", "pozisyon_kapat"
    minutes_since_open: int | None
    minutes_to_close: int | None
    can_open_position: bool
    should_close_positions: bool
    note: str


def get_session_state(now: datetime | None = None) -> SessionState:
    now = now or datetime.now()

    if now.weekday() in WEEKEND_DAYS:
        return SessionState(
            is_open=False, phase="kapali",
            minutes_since_open=None, minutes_to_close=None,
            can_open_position=False, should_close_positions=False,
            note="Hafta sonu - piyasa kapali. Bir sonraki islem gununu bekle.",
        )

    t = now.time()
    if t < MARKET_OPEN or t >= MARKET_CLOSE:
        return SessionState(
            is_open=False, phase="kapali",
            minutes_since_open=None, minutes_to_close=None,
            can_open_position=False, should_close_positions=False,
            note="Seans disi (BIST 10:00-18:00 arasi acik). Sinyaller sadece "
                 "bilgi amaclidir, emir bir sonraki acilista degerlenmelidir.",
        )

    open_dt = now.replace(hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0)
    close_dt = now.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute, second=0)
    since_open = int((now - open_dt).total_seconds() // 60)
    to_close = int((close_dt - now).total_seconds() // 60)

    if since_open < AVOID_AFTER_OPEN_MIN:
        return SessionState(
            is_open=True, phase="acilis_riskli",
            minutes_since_open=since_open, minutes_to_close=to_close,
            can_open_position=False, should_close_positions=False,
            note=f"Acilis sonrasi ilk {AVOID_AFTER_OPEN_MIN} dk - gap ve asiri "
                 f"volatilite riski. Yeni pozisyon icin {AVOID_AFTER_OPEN_MIN - since_open} dk bekle.",
        )

    if to_close <= FORCE_CLOSE_BEFORE_MIN:
        return SessionState(
            is_open=True, phase="pozisyon_kapat",
            minutes_since_open=since_open, minutes_to_close=to_close,
            can_open_position=False, should_close_positions=True,
            note=f"Kapanisa {to_close} dk kaldi - gun-ici modda acik pozisyonlar "
                 f"kapatilmali (gece gap riski tasinmasin).",
        )

    if to_close <= AVOID_BEFORE_CLOSE_MIN:
        return SessionState(
            is_open=True, phase="kapanis_yakin",
            minutes_since_open=since_open, minutes_to_close=to_close,
            can_open_position=False, should_close_positions=False,
            note=f"Kapanisa {to_close} dk kaldi - yeni pozisyon acilmaz, "
                 f"mevcut pozisyonlar hedef/stop ile yonetilir.",
        )

    return SessionState(
        is_open=True, phase="normal",
        minutes_since_open=since_open, minutes_to_close=to_close,
        can_open_position=True, should_close_positions=False,
        note="Normal islem penceresi.",
    )


def next_market_open(now: datetime | None = None) -> datetime:
    """Bir sonraki acilis zamanini dondurur (hafta sonu atlar)."""
    now = now or datetime.now()
    candidate = now.replace(hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0)
    if now.time() >= MARKET_OPEN:
        candidate += timedelta(days=1)
    while candidate.weekday() in WEEKEND_DAYS:
        candidate += timedelta(days=1)
    return candidate
