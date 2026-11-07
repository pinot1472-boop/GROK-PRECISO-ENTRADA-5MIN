# IPDA BingX Bot v10

Extiende v9 (solo GRAB, cerca nivel, 5m obligatorio) con ideas del **Crypto Range Breakout**:

## Novedades v10
1. **Rango Asia UTC 00:00–08:00** → high/low diario como pool de liquidez  
2. **Filtro de ancho** `ASIA_MIN/MAX_WIDTH_PCT` (default 1.5%–12%)  
3. **+12 score** si el GRAB barre Asia high/low  
4. **SL anclado** al extremo Asia cuando aplica  
5. **Corte de entradas** desde `ENTRY_CUTOFF_HOUR=20` UTC  

No opera breakouts ciegos (CONT sigue off). Asia se usa para **GRAB / rechazo**.

## Railway
Pega `railway_vars.txt`, rellena Telegram (y BingX si LIVE).

## Variables nuevas
```
USE_ASIA_RANGE=true
ASIA_START_HOUR=0
ASIA_END_HOUR=8
ASIA_MIN_WIDTH_PCT=1.5
ASIA_MAX_WIDTH_PCT=12.0
ASIA_GRAB_BOOST=12
ASIA_NEAR_ATR=0.40
ASIA_ONLY=false
USE_ENTRY_CUTOFF=true
ENTRY_CUTOFF_HOUR=20
```

`ASIA_ONLY=true` fuerza a operar únicamente GRAB sobre el rango Asia.
