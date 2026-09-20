# CRYPTO-SCALP-BOT-V5.2

Structural-SL Telegram signal bot for MEXC USDT futures market data.

## Runtime variables
- TELEGRAM_BOT_TOKEN
- CHAT_ID
- LEVERAGE=30
- TP1_PCT=0.005
- TP2_PCT=0.007
- MAX_RISK_PCT=0.025
- MAX_CHASE_PCT=0.0025
- SCAN_SECONDS=30

The bot only analyzes market data and sends Telegram signals. It does not place trades automatically.
MEXC API key/secret are not required by this version; market data is read through public exchange endpoints.
