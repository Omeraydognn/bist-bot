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

NOT: Resmi tatiller ve yarim gunler asagida liste olarak tutulur.
Sabit milli tatiller her yil aynidir; dini bayramlar (ay takvimi)
yillik listeden okunur - yeni yil geldiginde listeye eklenmelidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

# BIST Pay Piyasasi ana seans (surekli islem) saatleri
MARKET_OPEN = time(10, 0)
MARKET_CLOSE = time(18, 0)
HALF_DAY_CLOSE = time(13, 0)  # arife / 28 Ekim yarim gunlerde erken kapanis

# Riskli pencereler (dakika)
AVOID_AFTER_OPEN_MIN = 15    # acilistan sonra ilk 15 dk yeni pozisyon acma
AVOID_BEFORE_CLOSE_MIN = 20  # kapanisa 20 dk kala yeni pozisyon acma
FORCE_CLOSE_BEFORE_MIN = 10  # kapanisa 10 dk kala acik pozisyonu kapat (gun-ici mod)

# Hafta sonu gunleri (Pazartesi=0 ... Pazar=6)
WEEKEND_DAYS = (5, 6)

# --- RESMI TATIL TAKVIMI -------------------------------------------
# Sabit milli tatiller (her yil ayni ay/gun): borsa TAM GUN kapali
FIXED_HOLIDAYS = {
    (1, 1),    # Yilbasi
    (4, 23),   # Ulusal Egemenlik ve Cocuk Bayrami
    (5, 1),    # Emek ve Dayanisma Gunu
    (5, 19),   # Ataturk'u Anma, Genclik ve Spor Bayrami
    (7, 15),   # Demokrasi ve Milli Birlik Gunu
    (8, 30),   # Zafer Bayrami
    (10, 29),  # Cumhuriyet Bayrami
}

# Dini bayramlar (ay takvimine gore kayar) - borsa TAM GUN kapali.
# Yeni yil basinda Borsa Istanbul'un resmi takvimi ile guncelle.
RELIGIOUS_HOLIDAYS = {
    # 2025
    date(2025, 3, 31), date(2025, 4, 1),                    # Ramazan Bayrami
    date(2025, 6, 6), date(2025, 6, 9),                     # Kurban Bayrami
    # 2026
    date(2026, 3, 20),                                       # Ramazan Bayrami
    date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29), # Kurban Bayrami
    # 2027 (yaklasik - resmi takvim aciklaninca dogrula)
    date(2027, 3, 9), date(2027, 3, 10), date(2027, 3, 11),  # Ramazan Bayrami
    date(2027, 5, 17), date(2027, 5, 18), date(2027, 5, 19), # Kurban Bayrami
}

# Yarim gunler: seans 13:00'te biter (arife gunleri + 28 Ekim)
HALF_DAYS_FIXED = {(10, 28)}
HALF_DAYS = {
    date(2026, 3, 19),   # Ramazan arifesi
    date(2026, 5, 26),   # Kurban arifesi
    date(2027, 3, 8),    # Ramazan arifesi (yaklasik)
}


def is_market_holiday(d: date) -> bool:
    """Borsanin tam gun kapali oldugu resmi tatil mi?"""
    return (d.month, d.day) in FIXED_HOLIDAYS or d in RELIGIOUS_HOLIDAYS


def is_half_day(d: date) -> bool:
    """Yarim gun (erken kapanis) mi?"""
    return (d.month, d.day) in HALF_DAYS_FIXED or d in HALF_DAYS


def now_istanbul() -> datetime:
    """Sunucu nerede olursa olsun Turkiye saatini dondurur."""
    return datetime.now(ISTANBUL_TZ)


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
    now = now or now_istanbul()

    if now.weekday() in WEEKEND_DAYS:
        return SessionState(
            is_open=False, phase="kapali",
            minutes_since_open=None, minutes_to_close=None,
            can_open_position=False, should_close_positions=False,
            note="Hafta sonu - piyasa kapali. Bir sonraki islem gununu bekle.",
        )

    if is_market_holiday(now.date()):
        return SessionState(
            is_open=False, phase="kapali",
            minutes_since_open=None, minutes_to_close=None,
            can_open_position=False, should_close_positions=False,
            note="Resmi tatil - Borsa Istanbul kapali. Bir sonraki islem gununu bekle.",
        )

    market_close = HALF_DAY_CLOSE if is_half_day(now.date()) else MARKET_CLOSE

    t = now.time()
    if t < MARKET_OPEN or t >= market_close:
        return SessionState(
            is_open=False, phase="kapali",
            minutes_since_open=None, minutes_to_close=None,
            can_open_position=False, should_close_positions=False,
            note="Seans disi (BIST 10:00-18:00 arasi acik). Sinyaller sadece "
                 "bilgi amaclidir, emir bir sonraki acilista degerlenmelidir.",
        )

    open_dt = now.replace(hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0)
    close_dt = now.replace(hour=market_close.hour, minute=market_close.minute, second=0)
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
    """Bir sonraki acilis zamanini dondurur (hafta sonu ve resmi tatilleri atlar)."""
    now = now or now_istanbul()
    candidate = now.replace(hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0)
    if now.time() >= MARKET_OPEN:
        candidate += timedelta(days=1)
    while candidate.weekday() in WEEKEND_DAYS or is_market_holiday(candidate.date()):
        candidate += timedelta(days=1)
    return candidate
