"""Telegram + estado en disco (volumen Railway /data)."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

import config

log = logging.getLogger("notify")


class Telegram:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._c = client
        self.enabled = bool(config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID)
        if not self.enabled:
            log.warning("Telegram sin configurar — solo logs")

    async def send(self, text: str) -> bool:
        if not self.enabled:
            log.info("[tg-off] %s", text[:200])
            return False
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
        try:
            r = await self._c.post(
                url,
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            ok = r.status_code == 200 and r.json().get("ok") is True
            if not ok:
                log.error("Telegram error: %s %s", r.status_code, r.text[:200])
            return ok
        except Exception as exc:  # noqa: BLE001
            log.error("Telegram falló: %s", exc)
            return False


class State:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {
            "closed": 0,
            "wins": 0,
            "losses": 0,
            "day": "",
            "day_trades": 0,
            "day_losses": 0,
            "open": {},
            "last_signal": {},
            "cooldown": {},
            "level_mem": {},
            "funding_prev": {},
            "oi_prev": {},
        }
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self.data.update(json.loads(self.path.read_text()))
        except Exception as exc:  # noqa: BLE001
            log.warning("State load: %s", exc)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2))
        except Exception as exc:  # noqa: BLE001
            log.warning("State save: %s", exc)

    def roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.data.get("day") != today:
            self.data["day"] = today
            self.data["day_trades"] = 0
            self.data["day_losses"] = 0
            self.save()

    def can_trade(self, symbol: str) -> bool:
        self.roll_day()
        if self.data["day_trades"] >= config.MAX_TRADES_DAY:
            return False
        if self.data["day_losses"] >= config.MAX_LOSSES_DAY:
            return False
        if len(self.data.get("open", {})) >= config.MAX_OPEN:
            return False
        cd = self.data.get("cooldown", {}).get(symbol, 0)
        if time.time() < cd:
            return False
        return True

    def mark_signal(self, symbol: str) -> None:
        self.data.setdefault("last_signal", {})[symbol] = time.time()
        self.data.setdefault("cooldown", {})[symbol] = time.time() + config.COOLDOWN_BARS
        self.data["day_trades"] = int(self.data.get("day_trades", 0)) + 1
        self.save()

    def remember_level(self, symbol: str, side: str, level: float, atr: float, bar_ts: float) -> None:
        """Guarda un nivel GRAB rechazado para detectar 2º toque."""
        mem = self.data.setdefault("level_mem", {})
        mem[symbol] = {
            "side": side,
            "level": float(level),
            "atr": float(atr),
            "ts": float(bar_ts),
            "src": "GRAB",
        }
        # limpia viejos
        now = time.time()
        max_age = getattr(__import__("config"), "LEVEL_MEM_BARS", 40) * 15 * 60
        for k in list(mem.keys()):
            if now - float(mem[k].get("ts", 0)) > max_age:
                del mem[k]
        self.save()

    def second_test(self, symbol: str, side: str, price: float, atr: float) -> bool:
        mem = self.data.get("level_mem") or {}
        item = mem.get(symbol)
        if not item:
            return False
        if item.get("side") != side:
            return False
        tol = float(getattr(__import__("config"), "LEVEL_MEM_TOL_ATR", 0.25)) * max(atr, item.get("atr", atr))
        return abs(float(price) - float(item["level"])) <= tol

    def set_funding_prev(self, m: dict) -> None:
        self.data["funding_prev"] = {k: float(v) for k, v in m.items()}
        self.save()

    def funding_velocity(self, symbol: str, current: float) -> float:
        prev = (self.data.get("funding_prev") or {}).get(symbol)
        if prev is None:
            return 0.0
        return float(current) - float(prev)

    def set_oi_prev(self, m: dict) -> None:
        self.data["oi_prev"] = {k: float(v) for k, v in m.items()}
        self.save()

    def oi_change_pct(self, symbol: str, current: float) -> float:
        prev = (self.data.get("oi_prev") or {}).get(symbol)
        if prev is None or prev <= 0 or current <= 0:
            return 0.0
        return (float(current) / float(prev) - 1.0) * 100.0
