"""Configuración IPDA BingX Bot v4."""
from __future__ import annotations
import os


def _str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _bool(n: str, d: bool = False) -> bool:
    return os.getenv(n, str(d)).strip().lower() in ("1", "true", "yes", "si", "sí")


def _float(n: str, d: float) -> float:
    try:
        return float(os.getenv(n, str(d)))
    except (TypeError, ValueError):
        return d


def _int(n: str, d: int) -> int:
    try:
        return int(os.getenv(n, str(d)))
    except (TypeError, ValueError):
        return d


MODE = os.getenv("MODE", "SIGNAL").strip().upper()
LIVE_CONFIRMED = _bool("LIVE_CONFIRMED", False)

BINGX_API_KEY = os.getenv("BINGX_API_KEY", "").strip()
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET", "").strip()
BINGX_BASE_URL = os.getenv("BINGX_BASE_URL", "https://open-api.bingx.com").strip()
RECV_WINDOW = _int("RECV_WINDOW", 5000)
POST_ONLY = _bool("POST_ONLY", True)

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
).strip()
TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or ""
).strip()

TIMEFRAME = os.getenv("TIMEFRAME", "15m").strip()
KLINE_LIMIT = _int("KLINE_LIMIT", 120)
SCAN_SEC = _int("SCAN_SEC", 90)
MAX_SYMBOLS = _int("MAX_SYMBOLS", 40)  # hard cap en bot
MIN_QUOTE_VOL_24H = _float("MIN_QUOTE_VOL_24H", 5_000_000)
EXCLUDE_PREFIXES = tuple(
    p.strip().upper()
    for p in os.getenv("EXCLUDE_PREFIXES", "USDC,EUR,BUSD,TUSD,NCCO,NCSI,NCS").split(",")
    if p.strip()
)
SYMBOLS = [
    s.strip().upper().replace("USDT", "-USDT") if "-" not in s.strip().upper() else s.strip().upper()
    for s in os.getenv("SYMBOLS", "").split(",")
    if s.strip()
]

LOOKBACK_A = _int("LOOKBACK_A", 20)
LOOKBACK_B = _int("LOOKBACK_B", 40)
SWEEP_WIN = _int("SWEEP_WIN", 3)
MIN_DEP_ATR = _float("MIN_DEP_ATR", 0.02)
MAX_DEP_ATR = _float("MAX_DEP_ATR", 0.55)
SWEEP_RVOL = _float("SWEEP_RVOL", 1.00)
ACC_BARS = _int("ACC_BARS", 2)
NEAR_ATR = _float("NEAR_ATR", 0.45)
MIN_SCORE = _int("MIN_SCORE", 42)
ALLOW_LONG = _bool("ALLOW_LONG", True)
ALLOW_SHORT = _bool("ALLOW_SHORT", True)
ATR_LEN = _int("ATR_LEN", 14)
VOL_LEN = _int("VOL_LEN", 20)

USE_XSEC_RVOL = _bool("USE_XSEC_RVOL", True)
XSEC_RVOL_PCT = _float("XSEC_RVOL_PCT", 45.0)
USE_BTC_LEAD = _bool("USE_BTC_LEAD", True)
BTC_LEAD_STRICT = _bool("BTC_LEAD_STRICT", False)
BTC_SYMBOL = os.getenv("BTC_SYMBOL", "BTC-USDT").strip()
USE_FUNDING_EDGE = _bool("USE_FUNDING_EDGE", True)
ABSORB_RVOL = _float("ABSORB_RVOL", 1.50)
ABSORB_BODY = _float("ABSORB_BODY", 0.35)
MAX_SIGNALS_CYCLE = _int("MAX_SIGNALS_CYCLE", 3)
USE_PINBAR_FALLBACK = _bool("USE_PINBAR_FALLBACK", True)

USE_BOX_AGE = _bool("USE_BOX_AGE", True)
BOX_AGE_MIN = _int("BOX_AGE_MIN", 3)
BOX_AGE_MAX = _int("BOX_AGE_MAX", 48)
BOX_MAX_TOUCHES = _int("BOX_MAX_TOUCHES", 4)

USE_RESIDUAL = _bool("USE_RESIDUAL", True)
RESID_BARS = _int("RESID_BARS", 6)
RESID_MIN_PCT = _float("RESID_MIN_PCT", 60.0)
USE_EXCLUSIVITY = _bool("USE_EXCLUSIVITY", True)
EXCL_BARS = _int("EXCL_BARS", 4)

USE_SESSION_RULES = _bool("USE_SESSION_RULES", True)
SESSION_SCORE_ADJ = os.getenv(
    "SESSION_SCORE_ADJ", "0-7:+8,7-12:0,12-16:-3,16-21:+5,21-24:+10"
).strip()
ASIA_GRAB_ONLY = _bool("ASIA_GRAB_ONLY", True)

FUNDING_GRAB_BOOST = _float("FUNDING_GRAB_BOOST", 8.0)

USE_META_CADENCE = _bool("USE_META_CADENCE", True)
META_WINDOW_SEC = _int("META_WINDOW_SEC", 7200)
META_MAX_SIGS = _int("META_MAX_SIGS", 6)
META_SCORE_BUMP = _int("META_SCORE_BUMP", 10)

USE_BTC_LAG = _bool("USE_BTC_LAG", True)
BTC_LAG_MAX_BARS = _int("BTC_LAG_MAX_BARS", 4)

# ── v4 ────────────────────────────────────────────────────────────────
# Estrés de universo: % de símbolos con rango > STRESS_ATR_MULT * ATR
USE_STRESS_FILTER = _bool("USE_STRESS_FILTER", True)
STRESS_ATR_MULT = _float("STRESS_ATR_MULT", 2.0)
STRESS_PCT = _float("STRESS_PCT", 30.0)  # si >=30% en estrés → solo GRAB/PIN
# Desplazamiento post-GRAB (cuerpo a favor)
USE_DISPLACE = _bool("USE_DISPLACE", True)
DISPLACE_ATR = _float("DISPLACE_ATR", 0.25)
# Informe diario Telegram (hora UTC)
DAILY_REPORT_UTC = _int("DAILY_REPORT_UTC", 7)
# Paralelismo de klines
KLINE_CONCURRENCY = _int("KLINE_CONCURRENCY", 8)
# Tras N losses del día, exigir más score
LOSS_SCORE_BUMP = _int("LOSS_SCORE_BUMP", 8)

RISK_PCT = _float("RISK_PCT", 0.85)
MAX_LEVERAGE = _float("MAX_LEVERAGE", 5.0)
SL_ATR = _float("SL_ATR", 0.35)
TP1_R = _float("TP1_R", 1.0)
TP2_R = _float("TP2_R", 2.0)
MAX_TRADES_DAY = _int("MAX_TRADES_DAY", 4)
MAX_LOSSES_DAY = _int("MAX_LOSSES_DAY", 2)
COOLDOWN_BARS = _int("COOLDOWN_SEC", 300)
MAX_OPEN = _int("MAX_OPEN", 3)

STATE_PATH = os.getenv("STATE_PATH", "/data/ipda_state.json")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_HTTP = _bool("LOG_HTTP", False)

# ── v5 edges únicos ───────────────────────────────────────────────────
# Memoria de nivel fallido: 2º toque tras GRAB en la misma zona
USE_LEVEL_MEMORY = _bool("USE_LEVEL_MEMORY", True)
LEVEL_MEM_BARS = _int("LEVEL_MEM_BARS", 40)      # caducidad ~10h en 15m
LEVEL_MEM_TOL_ATR = _float("LEVEL_MEM_TOL_ATR", 0.25)
LEVEL_MEM_BOOST = _int("LEVEL_MEM_BOOST", 14)

# Velocidad de funding (Δ funding entre ciclos)
USE_FUNDING_VELOCITY = _bool("USE_FUNDING_VELOCITY", True)
FUND_VEL_THRESH = _float("FUND_VEL_THRESH", 0.005)  # 0.005% change
FUND_VEL_BOOST = _int("FUND_VEL_BOOST", 7)

# Compresión → expansión (rank ATR corto/largo en el universo)
USE_COMPRESS_RANK = _bool("USE_COMPRESS_RANK", True)
COMPRESS_SHORT = _int("COMPRESS_SHORT", 5)
COMPRESS_LONG = _int("COMPRESS_LONG", 30)
COMPRESS_PCT_MAX = _float("COMPRESS_PCT_MAX", 35.0)  # estaba comprimido si percentil <= esto
EXPAND_RVOL = _float("EXPAND_RVOL", 1.25)

# v6 research edges
USE_OI_EDGE = _bool("USE_OI_EDGE", True)
OI_CHANGE_MIN = _float("OI_CHANGE_MIN", 0.8)  # % cambio OI entre ciclos
OI_BOOST = _int("OI_BOOST", 8)
USE_BASIS_EDGE = _bool("USE_BASIS_EDGE", True)
BASIS_BPS_EXTREME = _float("BASIS_BPS_EXTREME", 8.0)
BASIS_BOOST = _int("BASIS_BOOST", 6)
USE_COND_FUNDING = _bool("USE_COND_FUNDING", True)
COND_FUND_EXTREME = _float("COND_FUND_EXTREME", 0.03)  # %


# ── Confirmación 5m (entrada precisa) ───────────────────────────────
USE_CONFIRM_5M = _bool("USE_CONFIRM_5M", True)
CONFIRM_INTERVAL = _str("CONFIRM_INTERVAL", "5m")
CONFIRM_MAX_DIST_ATR = _float("CONFIRM_MAX_DIST_ATR", 0.75)
CONFIRM_MIN_WICK_ATR = _float("CONFIRM_MIN_WICK_ATR", 0.12)
CONFIRM_MIN_BODY_ATR = _float("CONFIRM_MIN_BODY_ATR", 0.08)
CONFIRM_RVOL_MIN = _float("CONFIRM_RVOL_MIN", 0.90)
CONFIRM_SL_PAD_ATR = _float("CONFIRM_SL_PAD_ATR", 0.12)
# Si True: sin confirmación 5m no se envía señal ni se opera
CONFIRM_REQUIRED = _bool("CONFIRM_REQUIRED", False)


# ── v8 · edges novedosos ────────────────────────────────────────────
# Quarter-hour clock pulse (Kim & Hansen 2026): bursts at :00/:15/:30/:45
# Preferimos entradas 2–10 min DESPUÉS del pulso (estructura limpia post-algo)
USE_CLOCK_PULSE = _bool("USE_CLOCK_PULSE", True)
CLOCK_BOOST = _int("CLOCK_BOOST", 10)
CLOCK_PENALTY = _int("CLOCK_PENALTY", 6)  # dentro de los primeros 90s del pulso
# Residual momentum corto (retorno residual vs BTC, 4–8 barras 15m)
USE_RESID_MOM = _bool("USE_RESID_MOM", True)
RESID_MOM_BARS = _int("RESID_MOM_BARS", 6)
RESID_MOM_BOOST = _int("RESID_MOM_BOOST", 8)
# Soft-confirm: si 5m no confirma, aún avisa con score penalizado
CONFIRM_SOFT_PENALTY = _int("CONFIRM_SOFT_PENALTY", 12)
# Diagnose: log top near-misses every cycle
LOG_NEAR_MISSES = _bool("LOG_NEAR_MISSES", True)
