"""IPDA BingX Bot v5 — stress, displace, daily report, parallel klines."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import numpy as np

import config
from confirm_5m import confirm_entry
from bingx import BingX, BingXError
from notify import State, Telegram
from strategy import (
    BtcRegime,
    Signal,
    analyze,
    apply_cross_sectional,
    minutes_to_funding,
    session_bucket,
)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ipda")
STOP = asyncio.Event()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_recent_sigs: list[float] = []
_cycle_stats = {"cycles": 0, "cands": 0, "sigs": 0, "by_src": {}}
_last_report_day = ""


def _handle_sig(*_):
    log.info("Parada")
    STOP.set()


def meta_score_floor(state: State) -> int:
    now = time.time()
    global _recent_sigs
    _recent_sigs = [t for t in _recent_sigs if now - t <= config.META_WINDOW_SEC]
    floor = config.MIN_SCORE
    if config.USE_META_CADENCE and len(_recent_sigs) >= config.META_MAX_SIGS:
        floor += config.META_SCORE_BUMP
        log.info("Meta-cadencia: %d sigs recientes → floor %d", len(_recent_sigs), floor)
    # Tras pérdidas del día, más exigente
    losses = int(state.data.get("day_losses", 0) or 0)
    if losses >= 1:
        floor += config.LOSS_SCORE_BUMP * min(losses, 2)
    return floor


def fmt_sig(s: Signal, mode: str, stress: bool) -> str:
    arrow = "🟢 LONG" if s.side == "LONG" else "🔴 SHORT"
    live = "LIVE" if mode == "LIVE" else "SOLO SEÑAL"
    abs_t = " · ABSORCIÓN" if s.absorb else ""
    sec = " · 🎯 2º TOQUE" if getattr(s, "second_test", False) else ""
    st = " · ⚠ STRESS" if stress else ""
    return (
        f"<b>IPDA v8 · {arrow}</b> · {live}{abs_t}{sec}{st}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Par: <b>{s.symbol}</b>\n"
        f"Origen: {s.src} · Score <b>{s.score}/100</b>\n"
        f"XSec p{s.xsec_pct:.0f} · Resid p{s.resid_pct:.0f} · Excl p{s.excl_pct:.0f}\n"
        f"Caja age={s.box_age} toques={s.box_touches} · Sesión {s.session}\n"
        f"BTC: {'alineado ✓' if s.btc_aligned else 'divergente'} · Fund {s.funding_min:.0f}m\n"
        f"\n"
        f"📍 Entrada: <code>{s.entry}</code>\n"
        f"🛑 SL: <code>{s.sl}</code>\n"
        f"🎯 TP1: <code>{s.tp1}</code> · TP2: <code>{s.tp2}</code>\n"
        f"\n"
        f"RVOL {s.rvol:.2f}x · Dist {s.dist_atr:.2f} ATR · Resid {s.resid:+.2f}%\n"        f"OI {getattr(s,'oi_chg',0):+.1f}% · Basis {getattr(s,'basis_bps',0):+.1f} bps\n"
        f"{s.reason}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"5m: {getattr(s, "confirm_tag", "—")}\n"
        f"TF {config.TIMEFRAME} · MODE={mode}"
    )


async def pick_symbols(bx: BingX) -> list[str]:
    if config.SYMBOLS:
        syms = list(config.SYMBOLS)
    else:
        try:
            all_syms = await bx.symbols()
            vols = await bx.tickers_24h()
            ranked = sorted(
                (s for s in all_syms if vols.get(s, 0) >= config.MIN_QUOTE_VOL_24H),
                key=lambda s: vols.get(s, 0),
                reverse=True,
            )
            syms = ranked[: config.MAX_SYMBOLS]
        except Exception as exc:
            log.error("simbolos: %s", exc)
            syms = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
    btc = config.BTC_SYMBOL
    if config.USE_BTC_LEAD:
        syms = [btc] + [s for s in syms if s != btc]
    cap = max(5, min(int(config.MAX_SYMBOLS), 60))
    return syms[:cap]


def _bar_stress(rows: list[dict]) -> bool:
    """True si la última vela cerrada tiene rango > STRESS_ATR_MULT * ATR simple."""
    if len(rows) < 20:
        return False
    h = [r["high"] for r in rows]
    l = [r["low"] for r in rows]
    c = [r["close"] for r in rows]
    i = len(c) - 2
    trs = []
    for j in range(max(1, i - 14), i + 1):
        trs.append(max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])))
    atr = sum(trs) / len(trs) if trs else 0
    if atr <= 0:
        return False
    return (h[i] - l[i]) >= config.STRESS_ATR_MULT * atr


async def fetch_klines_batch(
    bx: BingX, symbols: list[str]
) -> dict[str, list[dict]]:
    sem = asyncio.Semaphore(config.KLINE_CONCURRENCY)
    out: dict[str, list[dict]] = {}

    async def one(sym: str):
        async with sem:
            try:
                rows = await bx.klines(sym, config.TIMEFRAME, config.KLINE_LIMIT)
                if rows:
                    out[sym] = rows
            except Exception as exc:
                log.debug("klines %s: %s", sym, exc)

    await asyncio.gather(*[one(s) for s in symbols])
    return out


async def try_live_order(bx: BingX, sig: Signal, equity: float) -> Optional[str]:
    risk_cash = equity * (config.RISK_PCT / 100.0)
    risk_px = abs(sig.entry - sig.sl)
    if risk_px <= 0 or equity <= 0:
        return None
    qty = min(risk_cash / risk_px, (equity * config.MAX_LEVERAGE) / sig.entry)
    qty = bx.round_qty(sig.symbol, qty)
    if qty < bx.min_qty(sig.symbol):
        return None
    side = "BUY" if sig.side == "LONG" else "SELL"
    pos_side = "LONG" if sig.side == "LONG" else "SHORT"
    sl = bx.round_price(sig.symbol, sig.sl)
    tp = bx.round_price(sig.symbol, sig.tp1)
    try:
        data = await bx._private(
            "POST", "/openApi/swap/v2/trade/order",
            {"symbol": sig.symbol, "side": side, "positionSide": pos_side,
             "type": "MARKET", "quantity": qty},
        )
        oid = str(data.get("orderId") or data.get("orderID") or "ok")
        exit_side = "SELL" if side == "BUY" else "BUY"
        for typ, px in (("STOP_MARKET", sl), ("TAKE_PROFIT_MARKET", tp)):
            await bx._private(
                "POST", "/openApi/swap/v2/trade/order",
                {"symbol": sig.symbol, "side": exit_side, "positionSide": pos_side,
                 "type": typ, "stopPrice": px, "quantity": qty, "workingType": "MARK_PRICE"},
            )
        return oid
    except BingXError as exc:
        log.error("LIVE %s: %s", sig.symbol, exc)
        return None


async def maybe_daily_report(tg: Telegram, state: State) -> None:
    global _last_report_day, _cycle_stats
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    if now.hour != config.DAILY_REPORT_UTC:
        return
    if _last_report_day == day:
        return
    _last_report_day = day
    by = _cycle_stats.get("by_src") or {}
    src_txt = ", ".join(f"{k}:{v}" for k, v in sorted(by.items())) or "—"
    await tg.send(
        f"<b>IPDA v8 · Informe diario</b> ({day} UTC)\n"
        f"Ciclos: {_cycle_stats['cycles']}\n"
        f"Candidatos: {_cycle_stats['cands']} · Señales: {_cycle_stats['sigs']}\n"
        f"Por origen: {src_txt}\n"
        f"Trades día (state): {state.data.get('day_trades', 0)} · "
        f"Losses: {state.data.get('day_losses', 0)}\n"
        f"Sesión ahora: {session_bucket()}"
    )
    _cycle_stats = {"cycles": 0, "cands": 0, "sigs": 0, "by_src": {}}


async def scan_once(bx, tg, state, symbols, mode, funding_map) -> BtcRegime:
    state.roll_day()
    equity = 0.0
    if mode == "LIVE":
        try:
            equity = (await bx.cuenta()).get("equity", 0.0) or await bx.balance_usdt()
        except Exception as exc:
            log.warning("balance: %s", exc)

    floor = meta_score_floor(state)
    data = await fetch_klines_batch(bx, symbols)

    # Estrés de universo
    stressed = 0
    total = 0
    for sym, rows in data.items():
        total += 1
        if _bar_stress(rows):
            stressed += 1
    stress_pct = (stressed / total * 100.0) if total else 0.0
    universe_stress = (
        config.USE_STRESS_FILTER and stress_pct >= config.STRESS_PCT
    )
    if universe_stress:
        log.info("STRESS universo %.0f%% (%d/%d) → solo GRAB/PIN", stress_pct, stressed, total)

    # Premium / basis (una sola llamada)
    premium = {}
    try:
        premium = await bx.premium_index()
    except Exception as exc:
        log.debug("premium: %s", exc)

    # OI solo top símbolos (rate limit) — paralelo limitado
    oi_map: dict[str, float] = {}
    if config.USE_OI_EDGE:
        sem_oi = asyncio.Semaphore(5)

        async def _oi(sym: str):
            async with sem_oi:
                try:
                    oi_map[sym] = await bx.open_interest(sym)
                except Exception:
                    oi_map[sym] = 0.0

        await asyncio.gather(*[_oi(s) for s in list(data.keys())[: min(25, len(data))]])

    btc_regime = BtcRegime()
    btc_closes: Optional[np.ndarray] = None
    candidates: list[Signal] = []

    # BTC primero
    btc = config.BTC_SYMBOL
    if btc in data:
        rows = data[btc]
        btc_closes = np.array([r["close"] for r in rows], dtype=float)
        fr = float(funding_map.get(btc, 0.0))
        oi_c = state.oi_change_pct(btc, oi_map.get(btc, 0.0))
        bps = float((premium.get(btc) or {}).get("basis_bps") or 0)
        sig = analyze(btc, rows, fr, None, None, universe_stress, 0.0, 0.0, oi_c, bps)
        if sig:
            btc_regime = BtcRegime(
                side=sig.side, src=sig.src, score=sig.score,
                ts=time.time(), bar_index=len(rows) - 2, ret=sig.ret_n,
            )
            log.info("BTC régimen → %s %s score=%s", sig.side, sig.src, sig.score)

    for sym, rows in data.items():
        if STOP.is_set():
            break
        if sym == btc:
            continue
        fr = float(funding_map.get(sym, 0.0))
        fv = state.funding_velocity(sym, fr)
        oi_c = state.oi_change_pct(sym, oi_map.get(sym, 0.0))
        bps = float((premium.get(sym) or {}).get("basis_bps") or 0)
        pre_long = state.second_test(sym, "LONG", float(rows[-2]["close"]), 1.0)
        pre_short = state.second_test(sym, "SHORT", float(rows[-2]["close"]), 1.0)
        sig = analyze(
            sym, rows, fr, btc_regime, btc_closes, universe_stress,
            second_test_hit=(pre_long or pre_short),
            fund_vel=fv,
            oi_chg=oi_c,
            basis_bps=bps,
        )
        if not sig:
            continue
        # revalida 2º toque con lado y ATR reales
        if config.USE_LEVEL_MEMORY and state.second_test(sym, sig.side, sig.entry, sig.atr):
            if not sig.second_test:
                sig.second_test = True
                sig.score = min(100, sig.score + config.LEVEL_MEM_BOOST)

        if not state.can_trade(sym):
            continue
        last = state.data.get("last_signal", {}).get(sym, 0)
        if time.time() - float(last) < config.COOLDOWN_BARS:
            continue
        candidates.append(sig)

    final = apply_cross_sectional(candidates, score_floor=floor)
    final = final[: config.MAX_SIGNALS_CYCLE]

    _cycle_stats["cycles"] += 1
    _cycle_stats["cands"] += len(candidates)
    _cycle_stats["sigs"] += len(final)

    for sig in final:
        # ── Confirmación 5m (entrada precisa) ──
        sig.confirm_tag = "sin 5m"
        if getattr(config, "USE_CONFIRM_5M", True):
            try:
                rows5 = await bx.klines(
                    sig.symbol,
                    getattr(config, "CONFIRM_INTERVAL", "5m"),
                    limit=80,
                )
            except Exception as exc:
                log.warning("5m %s: %s", sig.symbol, exc)
                rows5 = []
            ok5, why5, entry5, sl5 = confirm_entry(
                sig.side, sig.src, getattr(sig, "level_px", 0.0) or sig.entry, rows5
            )
            if ok5:
                risk_old = abs(sig.entry - sig.sl) or 1e-12
                tp1_r = abs(sig.tp1 - sig.entry) / risk_old
                tp2_r = abs(sig.tp2 - sig.entry) / risk_old
                sig.entry = entry5
                sig.sl = sl5
                risk = abs(sig.entry - sig.sl)
                if sig.side == "LONG":
                    sig.tp1 = sig.entry + tp1_r * risk
                    sig.tp2 = sig.entry + tp2_r * risk
                else:
                    sig.tp1 = sig.entry - tp1_r * risk
                    sig.tp2 = sig.entry - tp2_r * risk
                sig.confirm_tag = why5
                sig.score = min(100, sig.score + 8)
                sig.reason = f"{sig.reason} · 5m:{why5}"
            else:
                sig.confirm_tag = f"soft ({why5})"
                log.info("5m soft %s %s: %s", sig.symbol, sig.side, why5)
                if getattr(config, "CONFIRM_REQUIRED", False):
                    continue
                # Soft mode: avisa igual con score reducido (sigue siendo útil)
                pen = int(getattr(config, "CONFIRM_SOFT_PENALTY", 12))
                sig.score = max(0, sig.score - pen)
                if sig.score < floor:
                    log.info("5m soft drop %s sc=%s < floor %s", sig.symbol, sig.score, floor)
                    continue

        _cycle_stats["by_src"][sig.src] = _cycle_stats["by_src"].get(sig.src, 0) + 1
        log.info(
            "SEÑAL %s %s score=%s 5m=%s xsec=p%.0f %s",
            sig.side, sig.symbol, sig.score, sig.confirm_tag,
            sig.xsec_pct, sig.src,
        )
        await tg.send(fmt_sig(sig, mode, universe_stress))
        state.mark_signal(sig.symbol)
        if config.USE_LEVEL_MEMORY and sig.src in ("GRAB", "PIN") and sig.level_px > 0:
            state.remember_level(sig.symbol, sig.side, sig.level_px, sig.atr, time.time())
        _recent_sigs.append(time.time())

        if mode == "LIVE" and config.LIVE_CONFIRMED and equity > 0:
            oid = await try_live_order(bx, sig, equity)
            if oid:
                state.data.setdefault("open", {})[sig.symbol] = {
                    "side": sig.side, "entry": sig.entry, "sl": sig.sl,
                    "tp": sig.tp1, "ts": time.time(), "oid": oid,
                }
                state.save()
                await tg.send(f"✅ Orden <b>{sig.symbol}</b> {sig.side}")
            else:
                await tg.send(f"⚠️ {sig.symbol} señal OK, orden rechazada")

    log.info(
        "Ciclo: %d cand → %d sig | BTC=%s | floor=%d | sess=%s | stress=%.0f%%",
        len(candidates), len(final), btc_regime.side or "—", floor,
        session_bucket(), stress_pct,
    )
    if candidates and not final:
        for s in sorted(candidates, key=lambda x: x.score, reverse=True)[:3]:
            log.info(
                "  cerca: %s %s sc=%s rvol=%.2f resid=%+.2f age=%d %s",
                s.side, s.symbol, s.score, s.rvol, s.resid, s.box_age, s.src,
            )

    if config.USE_FUNDING_VELOCITY and funding_map:
        state.set_funding_prev(funding_map)
    if config.USE_OI_EDGE and oi_map:
        state.set_oi_prev(oi_map)
    await maybe_daily_report(tg, state)
    return btc_regime


async def main() -> None:
    mode = config.MODE
    if mode == "LIVE" and not config.LIVE_CONFIRMED:
        mode = "SIGNAL"
    if mode == "LIVE" and not (config.BINGX_API_KEY and config.BINGX_API_SECRET):
        mode = "SIGNAL"

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    state = State(config.STATE_PATH)
    async with httpx.AsyncClient() as client:
        bx = BingX(client)
        tg = Telegram(client)
        symbols = await pick_symbols(bx)
        await tg.send(
            f"<b>IPDA v8</b> arrancado\n"
            f"Modo: <b>{mode}</b> · TF {config.TIMEFRAME} · {len(symbols)} sym\n"
            f"Edges: ClockPulse·ResidMom·OI·Basis·Mem·FundVel·XSec\n"
            f"Sesión UTC: {session_bucket()} · Fund ~{minutes_to_funding():.0f}m\n"
            f"score≥{config.MIN_SCORE} · stress≥{config.STRESS_PCT:.0f}% → solo GRAB\n"
            f"Informe diario {config.DAILY_REPORT_UTC}:00 UTC"
        )

        cycle = 0
        while not STOP.is_set():
            t0 = time.time()
            funding_map = {}
            try:
                funding_map = await bx.funding_rates()
            except Exception as exc:
                log.debug("funding: %s", exc)
            try:
                await scan_once(bx, tg, state, symbols, mode, funding_map)
            except Exception as exc:
                log.exception("scan: %s", exc)
            cycle += 1
            if cycle % 15 == 0:
                symbols = await pick_symbols(bx)
                await tg.send(
                    f"💓 Heartbeat · {len(symbols)} sym · "
                    f"trades día {state.data.get('day_trades', 0)} · "
                    f"sess {session_bucket()} · "
                    f"sigs hoy {_cycle_stats['sigs']}"
                )
            wait = max(5.0, config.SCAN_SEC - (time.time() - t0))
            try:
                await asyncio.wait_for(STOP.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        await tg.send("🛑 IPDA v8 detenido")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
