"""
Confirmación de entrada en 5m (ejecución precisa).

Tras un setup 15m (GRAB/PIN/CONT), solo se valida la entrada si en 5m:
  - el precio está cerca del nivel
  - hay rechazo (mecha + cierre a favor) o aceptación según el tipo
  - RVOL razonable
  - distancia al nivel no excesiva

Esto NO inventa señales: filtra las de 15m para entrar mejor.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

import config


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> float:
    if len(c) < n + 1:
        return float(np.mean(h - l)) if len(c) else 0.0
    prev = np.roll(c, 1)
    prev[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return float(np.mean(tr[-n:]))


def confirm_entry(
    side: str,
    src: str,
    level_px: float,
    rows_5m: list[dict[str, Any]],
) -> tuple[bool, str, float, float]:
    """
    Returns:
        ok, reason, entry_hint, sl_hint
    """
    if not rows_5m or len(rows_5m) < 30:
        return False, "pocas velas 5m", 0.0, 0.0

    o = np.array([float(r["open"]) for r in rows_5m], dtype=float)
    h = np.array([float(r["high"]) for r in rows_5m], dtype=float)
    l = np.array([float(r["low"]) for r in rows_5m], dtype=float)
    c = np.array([float(r["close"]) for r in rows_5m], dtype=float)
    v = np.array([float(r.get("volume") or 0) for r in rows_5m], dtype=float)

    # Última vela CERRADA (evita repaint)
    i = len(c) - 2
    if i < 20:
        return False, "historial corto", 0.0, 0.0

    atr = _atr(h[: i + 1], l[: i + 1], c[: i + 1], 14)
    if atr <= 0:
        return False, "atr=0", 0.0, 0.0

    vol_sma = float(np.mean(v[i - 19 : i + 1]))
    rvol = float(v[i] / vol_sma) if vol_sma > 0 else 0.0

    level = float(level_px)
    if level <= 0:
        # fallback: extremo reciente
        level = float(np.min(l[i - 8 : i + 1])) if side == "LONG" else float(np.max(h[i - 8 : i + 1]))

    dist = abs(c[i] - level) / atr
    max_dist = float(getattr(config, "CONFIRM_MAX_DIST_ATR", 0.55))
    if dist > max_dist:
        return False, f"lejos nivel ({dist:.2f} ATR)", 0.0, 0.0

    upper_w = h[i] - max(o[i], c[i])
    lower_w = min(o[i], c[i]) - l[i]
    body = abs(c[i] - o[i])
    min_wick = float(getattr(config, "CONFIRM_MIN_WICK_ATR", 0.20)) * atr
    min_body = float(getattr(config, "CONFIRM_MIN_BODY_ATR", 0.15)) * atr
    rvol_min = float(getattr(config, "CONFIRM_RVOL_MIN", 1.10))

    pad = float(getattr(config, "CONFIRM_SL_PAD_ATR", 0.12)) * atr
    src_u = (src or "").upper()

    # ── LONG ──
    if side == "LONG":
        near = l[i] <= level + 0.35 * atr
        # rechazo: mecha abajo + cierre por encima del nivel / mitad superior
        rejection = (
            near
            and lower_w >= min_wick
            and body >= min_body * 0.5
            and c[i] >= level
            and c[i] > o[i]
        )
        # aceptación (CONT): cierre claro por encima
        accept = (
            src_u in ("CONT", "BREAK", "RUPTURA")
            and c[i] > level
            and body >= min_body
            and c[i] > o[i]
        )
        if rvol < rvol_min and not (rejection and lower_w >= min_wick * 1.3):
            return False, f"RVOL bajo {rvol:.2f}x", 0.0, 0.0
        if rejection or accept:
            entry = float(c[i])
            # SL bajo el mínimo de la ventana de rechazo / sweep local
            swing_low = float(np.min(l[i - 6 : i + 1]))
            sl = min(swing_low, l[i]) - pad
            tag = "rechazo 5m" if rejection else "aceptación 5m"
            return True, tag, entry, sl
        return False, "sin rechazo/aceptación LONG 5m", 0.0, 0.0

    # ── SHORT ──
    if side == "SHORT":
        near = h[i] >= level - 0.35 * atr
        rejection = (
            near
            and upper_w >= min_wick
            and body >= min_body * 0.5
            and c[i] <= level
            and c[i] < o[i]
        )
        accept = (
            src_u in ("CONT", "BREAK", "RUPTURA")
            and c[i] < level
            and body >= min_body
            and c[i] < o[i]
        )
        if rvol < rvol_min and not (rejection and upper_w >= min_wick * 1.3):
            return False, f"RVOL bajo {rvol:.2f}x", 0.0, 0.0
        if rejection or accept:
            entry = float(c[i])
            swing_high = float(np.max(h[i - 6 : i + 1]))
            sl = max(swing_high, h[i]) + pad
            tag = "rechazo 5m" if rejection else "aceptación 5m"
            return True, tag, entry, sl
        return False, "sin rechazo/aceptación SHORT 5m", 0.0, 0.0

    return False, "lado inválido", 0.0, 0.0
