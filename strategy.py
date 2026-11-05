"""
IPDA v3 — edges diferenciales:
  1. Edad + toques de caja
  2. Residual vs BTC + exclusividad de movimiento (cross-sectional)
  3. Reglas por sesión UTC
  4. Funding como sesgo del GRAB
  5. Lead-lag BTC→alt
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import time

import numpy as np

import config


@dataclass
class Signal:
    symbol: str
    side: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    score: int
    src: str
    rvol: float
    atr: float
    dist_atr: float
    days_hint: float
    reason: str
    xsec_pct: float = 0.0
    funding_min: float = 999.0
    absorb: bool = False
    btc_aligned: bool = True
    box_age: int = 0
    box_touches: int = 0
    resid: float = 0.0
    resid_pct: float = 0.0
    excl_pct: float = 0.0
    session: str = ""
    ret_n: float = 0.0
    second_test: bool = False
    fund_vel: float = 0.0
    compress: float = 1.0  # atr_short/atr_long
    compress_pct: float = 50.0
    level_px: float = 0.0
    oi_chg: float = 0.0
    basis_bps: float = 0.0
    confirm_tag: str = "—"


@dataclass
class BtcRegime:
    side: Optional[str] = None
    src: Optional[str] = None
    score: int = 0
    ts: float = 0.0
    bar_index: int = 0
    ret: float = 0.0


def _atr(h, l, c, n: int) -> np.ndarray:
    prev = np.roll(c, 1)
    prev[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    out = np.full_like(tr, np.nan, dtype=float)
    if len(tr) < n:
        return out
    out[n - 1] = np.mean(tr[:n])
    for i in range(n, len(tr)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _rvol(v, n: int) -> np.ndarray:
    out = np.ones_like(v, dtype=float)
    for i in range(n, len(v)):
        m = np.mean(v[i - n : i])
        out[i] = v[i] / m if m > 0 else 1.0
    return out


def minutes_to_funding(now_ts: float | None = None) -> float:
    t = now_ts if now_ts is not None else time.time()
    day = int(t) % 86400
    for s in (0, 8 * 3600, 16 * 3600, 24 * 3600):
        if day < s:
            return (s - day) / 60.0
    return (24 * 3600 - day) / 60.0


def utc_hour() -> int:
    return int(time.gmtime().tm_hour)


def session_bucket(hour: int | None = None) -> str:
    h = hour if hour is not None else utc_hour()
    if 0 <= h < 7:
        return "0-7"
    if 7 <= h < 12:
        return "7-12"
    if 12 <= h < 16:
        return "12-16"
    if 16 <= h < 21:
        return "16-21"
    return "21-24"


def parse_session_adj() -> dict[str, int]:
    out = {"0-7": 8, "7-12": 0, "12-16": -3, "16-21": 5, "21-24": 10}
    raw = getattr(config, "SESSION_SCORE_ADJ", "")
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        try:
            out[k.strip()] = int(v.strip())
        except ValueError:
            pass
    return out


def session_score_adj() -> tuple[str, int]:
    b = session_bucket()
    adj = parse_session_adj().get(b, 0)
    return b, adj


def funding_edge(side: str, src: str, funding_rate_pct: float, mins: float) -> int:
    """Funding como SESGO de dirección, sobre todo en GRAB cerca del settlement."""
    if not config.USE_FUNDING_EDGE:
        return 0
    pts = 0
    boost = float(getattr(config, "FUNDING_GRAB_BOOST", 8.0))
    # Crowded longs (funding +) → favorece SHORT GRAB
    if funding_rate_pct >= 0.025:
        if side == "SHORT" and src in ("GRAB", "PIN"):
            pts += int(boost)
        elif side == "LONG":
            pts -= int(boost * 0.6)
    elif funding_rate_pct <= -0.025:
        if side == "LONG" and src in ("GRAB", "PIN"):
            pts += int(boost)
        elif side == "SHORT":
            pts -= int(boost * 0.6)
    if mins <= 45 and pts > 0:
        pts += 3 if mins <= 15 else 1
    if mins <= 45 and pts < 0:
        pts -= 1
    return pts


def box_stats(h, l, level: float, atr: float, end: int, look: int, is_res: bool) -> tuple[int, int]:
    """Edad (barras desde primer toque relevante) y nº de toques."""
    tol = 0.15 * atr
    first = -1
    touches = 0
    start = max(0, end - look)
    for j in range(start, end):
        hit = (is_res and h[j] >= level - tol) or ((not is_res) and l[j] <= level + tol)
        if hit:
            touches += 1
            if first < 0:
                first = j
    age = (end - first) if first >= 0 else look
    return int(age), int(touches)


def analyze(
    symbol: str,
    rows: list[dict],
    funding_rate_pct: float = 0.0,
    btc_regime: Optional[BtcRegime] = None,
    btc_closes: Optional[np.ndarray] = None,
    universe_stress: bool = False,
    second_test_hit: bool = False,
    fund_vel: float = 0.0,
    oi_chg: float = 0.0,
    basis_bps: float = 0.0,
    ret_1: float = 0.0,
) -> Optional[Signal]:
    need = max(config.LOOKBACK_B, 50) + config.ACC_BARS + config.SWEEP_WIN + 5
    if len(rows) < need:
        return None

    o = np.array([r["open"] for r in rows], dtype=float)
    h = np.array([r["high"] for r in rows], dtype=float)
    l = np.array([r["low"] for r in rows], dtype=float)
    c = np.array([r["close"] for r in rows], dtype=float)
    v = np.array([r["volume"] for r in rows], dtype=float)

    i = len(c) - 2
    if i < need - 2:
        return None

    atr = _atr(h, l, c, config.ATR_LEN)
    rvol_arr = _rvol(v, config.VOL_LEN)
    a = float(atr[i])
    if not np.isfinite(a) or a <= 0:
        return None

    acc = config.ACC_BARS
    win = config.SWEEP_WIN
    box_end = i - acc - win
    if box_end < config.LOOKBACK_B + 2:
        return None

    la, lb = config.LOOKBACK_A, config.LOOKBACK_B
    res_a = float(np.max(h[box_end - la : box_end]))
    sup_a = float(np.min(l[box_end - la : box_end]))
    res_b = float(np.max(h[box_end - lb : box_end]))
    sup_b = float(np.min(l[box_end - lb : box_end]))
    res = res_a if abs(res_a - c[i]) <= abs(res_b - c[i]) else res_b
    sup = sup_a if abs(c[i] - sup_a) <= abs(c[i] - sup_b) else sup_b

    # Edad / toques
    age_res, touch_res = box_stats(h, l, res, a, box_end, lb, True)
    age_sup, touch_sup = box_stats(h, l, sup, a, box_end, lb, False)

    sw_up = sw_dn = False
    dep_up = dep_dn = 0.0
    rvol_sw = 1.0
    absorb = False

    for j in range(box_end, box_end + win):
        rv = float(rvol_arr[j])
        body = abs(c[j] - o[j]) / a
        if h[j] > res and c[j] < res:
            d = (h[j] - res) / a
            if config.MIN_DEP_ATR <= d <= config.MAX_DEP_ATR:
                sw_up = True
                if d >= dep_up:
                    dep_up, rvol_sw = d, max(rvol_sw, rv)
                    if rv >= config.ABSORB_RVOL and body <= config.ABSORB_BODY:
                        absorb = True
        if l[j] < sup and c[j] > sup:
            d = (sup - l[j]) / a
            if config.MIN_DEP_ATR <= d <= config.MAX_DEP_ATR:
                sw_dn = True
                if d >= dep_dn:
                    dep_dn, rvol_sw = d, max(rvol_sw, rv)
                    if rv >= config.ABSORB_RVOL and body <= config.ABSORB_BODY:
                        absorb = True

    side = src = None
    box_age = box_touches = 0

    if sw_up and rvol_sw >= config.SWEEP_RVOL:
        below = sum(1 for k in range(box_end + win, i + 1) if c[k] < res)
        above = sum(1 for k in range(box_end + win, i + 1) if c[k] > res)
        if below >= 1 and c[i] <= res:
            side, src = "SHORT", "GRAB"
            box_age, box_touches = age_res, touch_res
        elif above >= 1 and c[i] > res and dep_up >= 0.18:
            side, src = "LONG", "CONT"
            box_age, box_touches = age_res, touch_res

    if side is None and sw_dn and rvol_sw >= config.SWEEP_RVOL:
        above = sum(1 for k in range(box_end + win, i + 1) if c[k] > sup)
        below = sum(1 for k in range(box_end + win, i + 1) if c[k] < sup)
        if above >= 1 and c[i] >= sup:
            side, src = "LONG", "GRAB"
            box_age, box_touches = age_sup, touch_sup
        elif below >= 1 and c[i] < sup and dep_dn >= 0.18:
            side, src = "SHORT", "CONT"
            box_age, box_touches = age_sup, touch_sup

    if side is None and getattr(config, "USE_PINBAR_FALLBACK", True):
        rv = float(rvol_arr[i])
        body = abs(c[i] - o[i])
        upper_w = h[i] - max(c[i], o[i])
        lower_w = min(c[i], o[i]) - l[i]
        rng = h[i] - l[i]
        if rng > 0 and rv >= config.SWEEP_RVOL * 0.85:
            if lower_w >= 0.45 * rng and body <= 0.45 * rng and abs(l[i] - sup) <= max(config.NEAR_ATR, 1.5) * a and c[i] >= sup:
                side, src, rvol_sw = "LONG", "PIN", rv
                absorb = rv >= config.ABSORB_RVOL
                box_age, box_touches = age_sup, touch_sup
            elif upper_w >= 0.45 * rng and body <= 0.45 * rng and abs(h[i] - res) <= max(config.NEAR_ATR, 1.5) * a and c[i] <= res:
                side, src, rvol_sw = "SHORT", "PIN", rv
                absorb = rv >= config.ABSORB_RVOL
                box_age, box_touches = age_res, touch_res

    if side is None:
        return None
    # Estrés de universo: no CONT (solo reversiones GRAB/PIN)
    if universe_stress and src == "CONT":
        return None
    if side == "LONG" and not config.ALLOW_LONG:
        return None
    if side == "SHORT" and not config.ALLOW_SHORT:
        return None


    # Desplazamiento post-señal (cuerpo a favor en vela de confirmación)
    if getattr(config, "USE_DISPLACE", True) and src in ("GRAB", "PIN"):
        body = c[i] - o[i]
        need = config.DISPLACE_ATR * a
        if side == "LONG" and body < need * 0.5:
            # no exige cuerpo enorme, pero sí no vela roja fuerte
            if body < -need:
                return None
        if side == "SHORT" and body > -need * 0.5:
            if body > need:
                return None

    # Sesión: Asia solo GRAB/PIN
    sess, sess_adj = session_score_adj()
    if config.USE_SESSION_RULES and config.ASIA_GRAB_ONLY and sess == "0-7":
        if src == "CONT":
            return None

    # BTC lead / lag
    btc_aligned = True
    if config.USE_BTC_LEAD and btc_regime and btc_regime.side and symbol not in (config.BTC_SYMBOL, "BTC-USDT"):
        if btc_regime.side != side:
            btc_aligned = False
            if config.BTC_LEAD_STRICT:
                return None
        elif config.USE_BTC_LAG and btc_regime.bar_index > 0:
            # alt debería ir DESPUÉS de BTC (mismo sentido reciente)
            lag = i - btc_regime.bar_index
            if lag < 0 or lag > config.BTC_LAG_MAX_BARS:
                # no es un follow típico; no bloquea pero no suma
                btc_aligned = btc_aligned and lag <= config.BTC_LAG_MAX_BARS + 2

    # Residual vs BTC (retorno propio - retorno BTC)
    n = config.RESID_BARS
    ret_n = float((c[i] / c[i - n] - 1.0) * 100.0) if i >= n and c[i - n] > 0 else 0.0
    if ret_1 == 0.0 and i >= 1 and c[i - 1] > 0:
        ret_1 = float((c[i] / c[i - 1] - 1.0) * 100.0)
    resid = ret_n
    if btc_closes is not None and len(btc_closes) > n and i >= n:
        # alinear por índice final (mismas N velas)
        try:
            btc_ret = float(btc_closes[-2] / btc_closes[-2 - n] - 1.0) * 100.0
            resid = ret_n - btc_ret
        except Exception:
            resid = ret_n

    # Edad de caja
    age_pts = 0
    if config.USE_BOX_AGE:
        if box_touches > config.BOX_MAX_TOUCHES:
            age_pts -= 8
        if config.BOX_AGE_MIN <= box_age <= config.BOX_AGE_MAX:
            age_pts += 8
        elif box_age > config.BOX_AGE_MAX:
            age_pts -= 6
        elif box_age < config.BOX_AGE_MIN:
            age_pts += 2  # nivel fresco

    entry = float(c[i])
    if side == "LONG":
        sl = min(sup, float(l[i])) - config.SL_ATR * a
        risk = entry - sl
        if risk <= 0 or risk > 3.5 * a:
            return None
        tp1, tp2 = entry + config.TP1_R * risk, entry + config.TP2_R * risk
        dist = abs(entry - sup) / a
    else:
        sl = max(res, float(h[i])) + config.SL_ATR * a
        risk = sl - entry
        if risk <= 0 or risk > 3.5 * a:
            return None
        tp1, tp2 = entry - config.TP1_R * risk, entry - config.TP2_R * risk
        dist = abs(res - entry) / a

    mins_f = minutes_to_funding()
    f_pts = funding_edge(side, src or "", funding_rate_pct, mins_f)

    score = 36
    if rvol_sw >= config.SWEEP_RVOL:
        score += 10
    if dist <= config.NEAR_ATR:
        score += 10
    if src in ("GRAB", "PIN"):
        score += 10
    if src == "CONT":
        score += 6
    if absorb:
        score += 8
    if btc_aligned and btc_regime and btc_regime.side:
        score += 6
    score += f_pts
    score += age_pts
    score += sess_adj if config.USE_SESSION_RULES else 0
    # residual a favor de la dirección
    if config.USE_RESIDUAL:
        if side == "LONG" and resid > 0:
            score += min(8, int(abs(resid) * 2))
        elif side == "SHORT" and resid < 0:
            score += min(8, int(abs(resid) * 2))
        elif side == "LONG" and resid < -0.3:
            score -= 4
        elif side == "SHORT" and resid > 0.3:
            score -= 4
    if i >= 50:
        ema = float(np.mean(c[i - 49 : i + 1]))
        if side == "LONG" and entry >= ema:
            score += 6
        elif side == "SHORT" and entry <= ema:
            score += 6
    if rvol_sw >= 1.6:
        score += 4
    # v5: segundo toque de nivel fallido
    if second_test_hit and getattr(config, "USE_LEVEL_MEMORY", True):
        score += int(getattr(config, "LEVEL_MEM_BOOST", 14))
    # v5: funding velocity a favor del GRAB
    if getattr(config, "USE_FUNDING_VELOCITY", True) and abs(fund_vel) >= getattr(config, "FUND_VEL_THRESH", 0.005):
        if src in ("GRAB", "PIN"):
            # funding subiendo → crowded long → favorece SHORT grab
            if fund_vel > 0 and side == "SHORT":
                score += int(getattr(config, "FUND_VEL_BOOST", 7))
            elif fund_vel < 0 and side == "LONG":
                score += int(getattr(config, "FUND_VEL_BOOST", 7))
            elif fund_vel > 0 and side == "LONG":
                score -= 4
            elif fund_vel < 0 and side == "SHORT":
                score -= 4
    # v6: OI + precio (matrix clásica)
    if getattr(config, "USE_OI_EDGE", True) and abs(oi_chg) >= getattr(config, "OI_CHANGE_MIN", 0.8):
        # OI↑ precio↑ = nuevos longs → favorece LONG CONT / penaliza SHORT GRAB puro
        # OI↑ precio↓ = nuevos shorts
        # OI↓ precio↑ = short covering → LONG
        # OI↓ precio↓ = long liq → SHORT
        if oi_chg > 0 and ret_1 > 0 and side == "LONG":
            score += int(getattr(config, "OI_BOOST", 8))
        elif oi_chg > 0 and ret_1 < 0 and side == "SHORT":
            score += int(getattr(config, "OI_BOOST", 8))
        elif oi_chg < 0 and ret_1 > 0 and side == "LONG" and src in ("GRAB", "PIN"):
            score += int(getattr(config, "OI_BOOST", 8))  # covering into reclaim
        elif oi_chg < 0 and ret_1 < 0 and side == "SHORT" and src in ("GRAB", "PIN"):
            score += int(getattr(config, "OI_BOOST", 8))
        elif oi_chg > 0 and ret_1 > 0 and side == "SHORT" and src == "GRAB":
            score -= 5  # no fades new long positioning lightly
        elif oi_chg > 0 and ret_1 < 0 and side == "LONG" and src == "GRAB":
            score -= 5

    # v6: basis extremo (mark vs index)
    if getattr(config, "USE_BASIS_EDGE", True) and abs(basis_bps) >= getattr(config, "BASIS_BPS_EXTREME", 8.0):
        if basis_bps > 0 and side == "SHORT" and src in ("GRAB", "PIN"):
            score += int(getattr(config, "BASIS_BOOST", 6))  # perp rico → fade
        elif basis_bps < 0 and side == "LONG" and src in ("GRAB", "PIN"):
            score += int(getattr(config, "BASIS_BOOST", 6))

    # v6: funding CONDICIONAL (Shek): extremo + dirección del día
    if getattr(config, "USE_COND_FUNDING", True):
        ext = getattr(config, "COND_FUND_EXTREME", 0.03)
        # funding_rate_pct ya está en scope via param - need funding in analyze
        pass

    # compresión local (ratio); rank se aplica en cross-sectional
    compress = 1.0
    cs, cl = getattr(config, "COMPRESS_SHORT", 5), getattr(config, "COMPRESS_LONG", 30)
    if i >= cl and getattr(config, "USE_COMPRESS_RANK", True):
        def _atr_n(n):
            prevc = np.roll(c, 1); prevc[0] = c[0]
            tr = np.maximum(h - l, np.maximum(np.abs(h - prevc), np.abs(l - prevc)))
            return float(np.mean(tr[i - n + 1 : i + 1]))
        a_s, a_l = _atr_n(cs), _atr_n(cl)
        compress = (a_s / a_l) if a_l > 0 else 1.0
        # estaba comprimido y ahora hay RVOL → bonus
        if compress <= 0.75 and rvol_sw >= getattr(config, "EXPAND_RVOL", 1.25):
            score += 8
    score = int(max(0, min(100, score)))

    min_needed = config.MIN_SCORE + (sess_adj if config.USE_SESSION_RULES else 0)
    # corte blando aquí; el duro en apply_cross_sectional + meta
    if score < max(28, min_needed - 22):
        return None

    reason = (
        f"{src}{'·2nd' if second_test_hit else ''} RVOL {rvol_sw:.2f}x · age {box_age}t{box_touches} · "
        f"resid {resid:+.2f}% · {sess} · fund {mins_f:.0f}m"
    )
    return Signal(
        symbol=symbol,
        side=side,
        entry=entry,
        sl=float(sl),
        tp1=float(tp1),
        tp2=float(tp2),
        score=score,
        src=src or "—",
        rvol=float(rvol_sw),
        atr=a,
        dist_atr=float(dist),
        days_hint=float(box_age) / 96.0,
        reason=reason,
        funding_min=float(mins_f),
        absorb=absorb,
        btc_aligned=btc_aligned,
        box_age=box_age,
        box_touches=box_touches,
        resid=float(resid),
        second_test=bool(second_test_hit),
        fund_vel=float(fund_vel),
        compress=float(compress),
        level_px=float(sup if side == 'LONG' else res),
        oi_chg=float(oi_chg),
        basis_bps=float(basis_bps),
        session=sess,
        ret_n=float(abs(ret_n)),
    )


def apply_cross_sectional(
    candidates: list[Signal],
    min_pct: float | None = None,
    score_floor: int | None = None,
) -> list[Signal]:
    if not candidates:
        return []
    floor = score_floor if score_floor is not None else config.MIN_SCORE
    pct_need = min_pct if min_pct is not None else config.XSEC_RVOL_PCT

    # Percentiles de residual y exclusividad dentro del ciclo
    if config.USE_RESIDUAL and len(candidates) >= 2:
        resids = sorted(abs(s.resid) for s in candidates)
        for s in candidates:
            s.resid_pct = sum(1 for x in resids if x <= abs(s.resid)) / len(resids) * 100.0
    if config.USE_EXCLUSIVITY and len(candidates) >= 2:
        rets = sorted(s.ret_n for s in candidates)
        for s in candidates:
            s.excl_pct = sum(1 for x in rets if x <= s.ret_n) / len(rets) * 100.0
    if getattr(config, "USE_COMPRESS_RANK", True) and len(candidates) >= 2:
        comps = sorted(s.compress for s in candidates)  # menor = más comprimido
        for s in candidates:
            # percentil bajo = más comprimido respecto al universo
            s.compress_pct = sum(1 for x in comps if x <= s.compress) / len(comps) * 100.0
            if s.compress_pct <= getattr(config, "COMPRESS_PCT_MAX", 35.0) and s.rvol >= getattr(config, "EXPAND_RVOL", 1.25):
                s.score = int(min(100, s.score + 6))

    if not config.USE_XSEC_RVOL:
        out = [s for s in candidates if s.score >= floor]
        out.sort(key=lambda x: x.score, reverse=True)
        return out

    if len(candidates) == 1:
        candidates[0].xsec_pct = 100.0
        candidates[0].resid_pct = 100.0
        candidates[0].excl_pct = 100.0
        return candidates if candidates[0].score >= floor else []

    rvols = sorted(s.rvol for s in candidates)
    out: list[Signal] = []
    for s in candidates:
        rank = sum(1 for x in rvols if x <= s.rvol) / len(rvols) * 100.0
        s.xsec_pct = rank
        need = pct_need if len(candidates) >= 4 else min(pct_need, 50.0)
        # boost por residual/exclusividad altos
        if s.resid_pct >= config.RESID_MIN_PCT:
            s.score = int(min(100, s.score + 5))
        if s.excl_pct >= config.RESID_MIN_PCT:
            s.score = int(min(100, s.score + 5))
        ok = s.score >= floor and rank >= need
        ok = ok or (s.score >= floor + 10 and rank >= need - 15)
        # residual extremo puede compensar
        if not ok and s.score >= floor and s.resid_pct >= 80:
            ok = True
        if ok:
            s.score = int(min(100, s.score + int(max(0, rank - need) / 5)))
            out.append(s)
    out.sort(key=lambda x: (x.score, x.xsec_pct, x.resid_pct), reverse=True)
    return out
