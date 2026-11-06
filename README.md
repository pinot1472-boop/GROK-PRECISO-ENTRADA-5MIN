# IPDA BingX Bot v8

Bot de señales (y opcionalmente ejecución) para **cripto perps BingX**, con lógica **IPDA**:

- Cajas de liquidez (lookback 20/40)
- Sweep (mecha fuera + cierre dentro + RVOL)
- Accept / Reject en 2–3 velas
- Score ≥ umbral → señal a **Telegram**
- Modo `SIGNAL` (solo avisos) o `LIVE` (órdenes en BingX)

Diseñado para desplegar en **Railway** desde **GitHub**.

---

## 1. Subir a GitHub

```bash
cd ipda-bingx-bot
git init
git add .
git commit -m "IPDA BingX bot v1"
# crea repo vacío en GitHub y:
git remote add origin https://github.com/TU_USUARIO/ipda-bingx-bot.git
git branch -M main
git push -u origin main
```

## 2. Railway

1. New Project → Deploy from GitHub → elige el repo  
2. Tipo de servicio: **Worker** (no web)  
3. Añade volumen: mount path `/data`  
4. Pega variables de `railway_vars.txt`  
5. Deploy  

El `Procfile` arranca: `python bot.py`.

## 3. Telegram

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → copia el **token**  
2. Escribe al bot → abre `https://api.telegram.org/bot<TOKEN>/getUpdates` → copia tu **chat id**  
3. Variables:
   - `TELEGRAM_TOKEN=...`
   - `TELEGRAM_CHAT_ID=...`

## 4. BingX (solo si MODE=LIVE)

1. API Key en BingX (permisos **futures trade**, **sin withdraw**)  
2. Variables:
   - `BINGX_API_KEY`
   - `BINGX_API_SECRET`
3. Primero `MODE=SIGNAL` varios días  
4. Luego:
   ```
   MODE=LIVE
   LIVE_CONFIRMED=true
   ```

## 5. Cómo opera

| Paso | Qué hace |
|------|----------|
| 1 | Cada `SCAN_SEC` (90s) pide klines 15m de top N perps por volumen |
| 2 | Calcula cajas, sweep, accept/reject, score |
| 3 | Si score ≥ `MIN_SCORE` → mensaje Telegram |
| 4 | Si LIVE + confirmado → market + SL/TP en BingX |
| 5 | Límites: máx trades/día, pérdidas/día, posiciones abiertas, cooldown |

## 6. Local (prueba)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export TELEGRAM_TOKEN=...
export TELEGRAM_CHAT_ID=...
export MODE=SIGNAL
python bot.py
```

## 7. Seguridad

- Nunca subas keys al repo  
- Empieza siempre en `SIGNAL`  
- `LIVE_CONFIRMED=true` es el fusible anti-error  
- Riesgo por trade bajo (`RISK_PCT=0.85`)  
- Monta volumen `/data` para no perder estado al redeploy  

## 8. Ajustes útiles

| Variable | Efecto |
|----------|--------|
| `MIN_SCORE=60` | Menos señales, más filtro |
| `TIMEFRAME=5m` | Más actividad, más ruido |
| `MAX_SYMBOLS=20` | Menos carga API |
| `ALLOW_SHORT=false` | Solo longs |

## Archivos

```
bot.py           → bucle principal
strategy.py      → IPDA (sweep / accept / score)
bingx.py         → cliente REST BingX
notify.py        → Telegram + state.json
config.py        → env vars
Procfile         → worker Railway
railway.toml
railway_vars.txt → plantilla de variables
requirements.txt
```


## Confirmación 5m (v7)

El bot analiza en **15m** y solo envía señal / opera si en **5m** hay:

- precio cerca del nivel
- rechazo (mecha + cierre a favor) o aceptación (CONT)
- RVOL mínimo

Variables:

```
USE_CONFIRM_5M=true
CONFIRM_REQUIRED=true
CONFIRM_INTERVAL=5m
```

Si `CONFIRM_REQUIRED=false`, avisa igual pero marca `espera (...)` cuando 5m no confirma.


## v8 · por qué ahora sí da señales + edge nuevo

### Relajaciones (antes bloqueaban todo)
- `MIN_SCORE` 48 → **42**
- `SWEEP_RVOL` 1.10 → **1.00**
- `XSEC_RVOL_PCT` 55 → **45**
- `CONFIRM_REQUIRED` **false** (modo soft: avisa con penalización si 5m no confirma)
- wick/body/dist 5m más tolerantes

### Edge novedoso: **Clock Pulse** (Kim & Hansen 2026, arXiv)
Los perps tienen bursts algorítmicos cada :00/:15/:30/:45.
- **+10 score** si estás 2–10 min *después* del pulso (estructura legible)
- **−6 score** en los primeros 90s del burst (ruido + peor fill)

Casi ningún bot retail IPDA usa el reloj de cuarto de hora como filtro de ejecución.

### Residual momentum corto
Alinea GRAB/PIN con el residual vs BTC de las últimas 6 velas 15m.
