# CRYPTO SCALP BOT V5.3 STRICT-0.50

Signal-only MEXC futures scanner. No orders are placed.

## What changed

V5.3 is intentionally stricter than V5.2 and is designed to reduce signal count in favor of continuation confirmation toward a first target of at least 0.50%.

A signal must pass:
- 1H and 15m directional context;
- 5m EMA context;
- recent liquidity sweep;
- displacement;
- POI retest and reaction;
- structure break / BOS;
- imbalance/FVG proximity;
- RSI(5m) directional range and direction;
- volume >= 0.80x its recent baseline;
- order-book imbalance in the signal direction (absolute minimum 0.10);
- latest closed 1m candle confirmation;
- anti-chase and structural-risk filters.

### RSI filter
- LONG: 51-60 and RSI rising.
- SHORT: 40-49 and RSI falling.

### Order-book filter
- LONG: OBI >= +0.10.
- SHORT: OBI <= -0.10.

### Volume filter
- Minimum 0.80x of the recent 20-candle 5m average.

## Telegram

Set `TELEGRAM_BOT_TOKEN` in Railway Variables. The token is intentionally not stored in the source code.
Set `CHAT_ID` (default in this package is the supplied group ID).

Never commit a real Telegram token to GitHub.

## Important

No filter can guarantee a 0.50% move after a signal. The 0.50% target is a selection criterion, not a guarantee. Validate the strategy on historical/OOS data before relying on it.
