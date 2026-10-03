import os
import time
import traceback

print("=== CRYPTO SCALP BOT V5.3 STRICT-0.50 STARTING ===", flush=True)

try:
    import ccxt
    import requests
    print("Imports OK", flush=True)
except Exception as e:
    print("IMPORT ERROR:", repr(e), flush=True)
    raise

SYMBOLS = [s.strip() for s in os.getenv(
    "SYMBOLS",
    "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,XRP/USDT:USDT,"
    "HBAR/USDT:USDT,FET/USDT:USDT,JUP/USDT:USDT,LINK/USDT:USDT,VIRTUAL/USDT:USDT"
).split(",") if s.strip()]
SCAN_SECONDS = max(15, int(os.getenv("SCAN_SECONDS", "30")))
COOLDOWN_SECONDS = max(60, int(os.getenv("COOLDOWN_SECONDS", "900")))
MIN_ROOM = float(os.getenv("MIN_ROOM", "0.005"))
MAX_ROOM = float(os.getenv("MAX_ROOM", "0.007"))
TP1_PCT = float(os.getenv("TP1_PCT", "0.005"))       # 0.50%
TP2_PCT = float(os.getenv("TP2_PCT", "0.007"))       # 0.70%
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT", "0.025"))
MAX_CHASE_PCT = float(os.getenv("MAX_CHASE_PCT", "0.0025"))
LEVERAGE = int(os.getenv("LEVERAGE", "30"))
HEARTBEAT_SECONDS = max(60, int(os.getenv("HEARTBEAT_SECONDS", "300")))

# Strict continuation filters. These deliberately reduce signal frequency.
RSI_LONG_MIN = float(os.getenv("RSI_LONG_MIN", "51"))
RSI_LONG_MAX = float(os.getenv("RSI_LONG_MAX", "60"))
RSI_SHORT_MIN = float(os.getenv("RSI_SHORT_MIN", "40"))
RSI_SHORT_MAX = float(os.getenv("RSI_SHORT_MAX", "49"))
OBI_MIN_ABS = float(os.getenv("OBI_MIN_ABS", "0.10"))
VOLUME_MIN_RATIO = float(os.getenv("VOLUME_MIN_RATIO", "0.80"))
HTF_REQUIRED = os.getenv("HTF_REQUIRED", "1").strip() != "0"
REQUIRE_RSI_DIRECTION = os.getenv("REQUIRE_RSI_DIRECTION", "1").strip() != "0"
REQUIRE_1M_CONFIRMATION = os.getenv("REQUIRE_1M_CONFIRMATION", "1").strip() != "0"

TG = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.getenv("CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", "-5318043930")).strip()
last_sent = {}
last_heartbeat = 0.0

print("Symbols:", ", ".join(SYMBOLS), flush=True)
print(
    f"STRICT target: >= {TP1_PCT*100:.2f}% | RSI LONG {RSI_LONG_MIN:.0f}-{RSI_LONG_MAX:.0f} | "
    f"RSI SHORT {RSI_SHORT_MIN:.0f}-{RSI_SHORT_MAX:.0f} | OBI abs >= {OBI_MIN_ABS:.2f} | "
    f"Volume >= {VOLUME_MIN_RATIO:.2f}x | HTF={HTF_REQUIRED} | 1m={REQUIRE_1M_CONFIRMATION}",
    flush=True,
)
print("Telegram configured:", bool(TG and CHAT), flush=True)
print("Chat ID configured:", CHAT if CHAT else "<empty>", flush=True)

ex = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def send(text):
    if not TG or not CHAT:
        print("[TG] NOT CONFIGURED", flush=True)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG}/sendMessage",
            json={"chat_id": CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        print(f"[TG] HTTP {r.status_code}", flush=True)
        if not r.ok:
            print("[TG] RESPONSE", r.text[:500], flush=True)
            return False
        return True
    except Exception as e:
        print("[TG ERROR]", repr(e), flush=True)
        return False


def fetch(symbol, timeframe, limit):
    try:
        return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        print(f"[FETCH ERROR] {symbol} {timeframe}: {e}", flush=True)
        return None


def fetch_orderbook(symbol):
    try:
        ob = ex.fetch_order_book(symbol, limit=20)
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        bid_vol = sum(float(x[1]) for x in bids[:10])
        ask_vol = sum(float(x[1]) for x in asks[:10])
        total = bid_vol + ask_vol
        if total <= 0:
            return 0.0
        return (bid_vol - ask_vol) / total
    except Exception as e:
        print(f"[ORDERBOOK ERROR] {symbol}: {e}", flush=True)
        return None


def ema(values, period):
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    x = float(values[0])
    for v in values[1:]:
        x = float(v) * k + x * (1 - k)
    return x


def context_5m(rows):
    closed = rows[:-1]
    if len(closed) < 60:
        return "NEUTRAL"
    closes = [r[4] for r in closed]
    e20 = ema(closes[-50:], 20)
    e50 = ema(closes[-60:], 50)
    return "LONG" if e20 > e50 else "SHORT" if e20 < e50 else "NEUTRAL"


def context_htf(rows):
    closed = rows[:-1]
    if len(closed) < 60:
        return "NEUTRAL"
    closes = [float(r[4]) for r in closed]
    e20 = ema(closes[-50:], 20)
    e50 = ema(closes[-60:], 50)
    return "LONG" if e20 > e50 else "SHORT" if e20 < e50 else "NEUTRAL"


def rsi(values, period=14):
    if len(values) < period + 2:
        return None
    gains = []
    losses = []
    for i in range(1, len(values)):
        delta = float(values[i]) - float(values[i - 1])
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def volume_ratio(rows, lookback=20):
    closed = rows[:-1]
    if len(closed) < lookback + 2:
        return None
    current = float(closed[-1][5])
    baseline = [float(r[5]) for r in closed[-lookback-1:-1]]
    avg = sum(baseline) / len(baseline) if baseline else 0.0
    return current / avg if avg > 0 else None


def median(values):
    vals = sorted(float(x) for x in values if x is not None)
    if not vals:
        return 0.0
    return vals[len(vals)//2]


def fvg_after(rows, side, start_idx):
    if len(rows) < 4:
        return None
    for i in range(len(rows)-1, max(start_idx+1, 2), -1):
        a, b, c = rows[i-2], rows[i-1], rows[i]
        if side == "LONG" and float(a[2]) < float(c[3]):
            return (float(a[2]), float(c[3]), i)
        if side == "SHORT" and float(a[3]) > float(c[2]):
            return (float(c[2]), float(a[3]), i)
    return None


def strict_momentum_checks(side, m5, m1):
    c5 = m5[:-1]
    c1 = m1[:-1]
    closes5 = [float(r[4]) for r in c5]
    if len(closes5) < 25 or len(c1) < 5:
        return None
    current_rsi = rsi(closes5, 14)
    previous_rsi = rsi(closes5[:-1], 14)
    vol = volume_ratio(m5, 20)
    if current_rsi is None or previous_rsi is None or vol is None:
        return None
    # 1m confirmation: latest closed candle must agree with the side and show
    # a close beyond the previous close. This reduces signals that immediately fade.
    c = c1[-1]
    p = c1[-2]
    if side == "SHORT":
        one_min_ok = float(c[4]) < float(c[1]) and float(c[4]) < float(p[4])
    else:
        one_min_ok = float(c[4]) > float(c[1]) and float(c[4]) > float(p[4])
    if REQUIRE_1M_CONFIRMATION and not one_min_ok:
        return {"ok": False, "rsi": current_rsi, "rsi_prev": previous_rsi, "volume": vol, "one_min_ok": False}
    if side == "SHORT":
        rsi_ok = RSI_SHORT_MIN <= current_rsi <= RSI_SHORT_MAX
        direction_ok = current_rsi < previous_rsi
    else:
        rsi_ok = RSI_LONG_MIN <= current_rsi <= RSI_LONG_MAX
        direction_ok = current_rsi > previous_rsi
    if REQUIRE_RSI_DIRECTION and not direction_ok:
        return {"ok": False, "rsi": current_rsi, "rsi_prev": previous_rsi, "volume": vol, "one_min_ok": one_min_ok}
    if not rsi_ok or vol < VOLUME_MIN_RATIO:
        return {"ok": False, "rsi": current_rsi, "rsi_prev": previous_rsi, "volume": vol, "one_min_ok": one_min_ok}
    return {"ok": True, "rsi": current_rsi, "rsi_prev": previous_rsi, "volume": vol, "one_min_ok": one_min_ok}



def detect(symbol):
    m5 = fetch(symbol, "5m", 150)
    m1 = fetch(symbol, "1m", 180)
    h1 = fetch(symbol, "1h", 100) if HTF_REQUIRED else None
    m15 = fetch(symbol, "15m", 100) if HTF_REQUIRED else None
    if not m5 or not m1 or len(m5) < 80 or len(m1) < 60:
        return None

    ctx = context_5m(m5)
    h1_ctx = context_htf(h1) if h1 else ctx
    m15_ctx = context_htf(m15) if m15 else ctx
    d = m1[:-1]
    if len(d) < 50:
        return None

    # Candidate setup first; strict momentum filters are applied only after the
    # structural side is known.
    e = d[-1]
    base_start = max(10, len(d)-60)
    sweep_idx = side = sweep_level = sweep_extreme = None
    preferred = ctx if ctx in ("LONG", "SHORT") else None
    candidates = []
    for i in range(len(d)-1, base_start-1, -1):
        prev = d[max(0, i-12):i]
        if len(prev) < 5:
            continue
        lo = min(float(r[3]) for r in prev)
        hi = max(float(r[2]) for r in prev)
        c = d[i]
        if float(c[3]) < lo and float(c[4]) > lo:
            candidates.append((i, "LONG", lo, float(c[3])))
        if float(c[2]) > hi and float(c[4]) < hi:
            candidates.append((i, "SHORT", hi, float(c[2])))
    if preferred:
        matching = [x for x in candidates if x[1] == preferred]
        chosen = matching[0] if matching else (candidates[0] if candidates else None)
    else:
        chosen = candidates[0] if candidates else None
    if chosen:
        sweep_idx, side, sweep_level, sweep_extreme = chosen
    if not side:
        print(f"[FILTER SWEEP] {symbol} no recent SSL/BSL sweep", flush=True)
        return None
    if ctx != side:
        print(f"[FILTER CONTEXT] {symbol} sweep={side} 5m={ctx}", flush=True)
        return None
    if HTF_REQUIRED and (h1_ctx != side or m15_ctx != side):
        print(f"[FILTER HTF] {symbol} side={side} 1h={h1_ctx} 15m={m15_ctx}", flush=True)
        return None

    # Strict RSI / volume / 1m momentum filter.
    strict = strict_momentum_checks(side, m5, m1)
    if not strict or not strict["ok"]:
        if strict:
            print(
                f"[FILTER MOMENTUM] {symbol} {side} RSI={strict['rsi']:.1f} "
                f"prev={strict['rsi_prev']:.1f} vol={strict['volume']:.2f}x "
                f"1m={strict['one_min_ok']}", flush=True
            )
        else:
            print(f"[FILTER MOMENTUM] {symbol} {side} insufficient data", flush=True)
        return None

    # Order-book imbalance must agree with the direction.
    obi = fetch_orderbook(symbol)
    if obi is None:
        print(f"[FILTER OBI] {symbol} {side} unavailable", flush=True)
        return None
    if side == "SHORT" and obi > -OBI_MIN_ABS:
        print(f"[FILTER OBI] {symbol} SHORT obi={obi:+.2f}", flush=True)
        return None
    if side == "LONG" and obi < OBI_MIN_ABS:
        print(f"[FILTER OBI] {symbol} LONG obi={obi:+.2f}", flush=True)
        return None

    bodies = [abs(float(r[4])-float(r[1])) for r in d[max(0, sweep_idx):len(d)-2]]
    med = median(bodies[-24:])
    disp_idx = None
    for i in range(sweep_idx+1, len(d)-1):
        c = d[i]
        body = abs(float(c[4])-float(c[1]))
        if side == "LONG" and float(c[4]) > float(c[1]) and body >= max(med*1.35, float(c[4])*0.0006):
            disp_idx = i
            break
        if side == "SHORT" and float(c[4]) < float(c[1]) and body >= max(med*1.35, float(c[4])*0.0006):
            disp_idx = i
            break
    if disp_idx is None:
        print(f"[FILTER DISPLACEMENT] {symbol} {side}", flush=True)
        return None

    poi_idx = max(sweep_idx, disp_idx-1)
    poi = d[poi_idx]
    poi_low = float(poi[3])
    poi_high = float(poi[2])
    retest_idx = None
    for i in range(max(poi_idx+1, disp_idx+1), len(d)-1):
        c = d[i]
        if float(c[3]) <= poi_high and float(c[2]) >= poi_low:
            retest_idx = i
            break
    if retest_idx is None or retest_idx >= len(d)-1:
        print(f"[FILTER POI] {symbol} {side} no POI retest", flush=True)
        return None

    reaction_idx = None
    for i in range(retest_idx+1, len(d)-1):
        c = d[i]
        if side == "LONG" and float(c[4]) > float(c[1]) and float(c[4]) > float(d[i-1][4]):
            reaction_idx = i
            break
        if side == "SHORT" and float(c[4]) < float(c[1]) and float(c[4]) < float(d[i-1][4]):
            reaction_idx = i
            break
    if reaction_idx is None:
        print(f"[FILTER REACTION] {symbol} {side}", flush=True)
        return None

    structure = d[max(0, retest_idx-4):retest_idx]
    if len(structure) < 2:
        return None
    local_high = max(float(r[2]) for r in structure)
    local_low = min(float(r[3]) for r in structure)
    bos_idx = None
    for i in range(reaction_idx, len(d)):
        c = d[i]
        if side == "LONG" and float(c[4]) > local_high:
            bos_idx = i
        if side == "SHORT" and float(c[4]) < local_low:
            bos_idx = i
    if bos_idx is None:
        print(f"[FILTER BOS] {symbol} {side}", flush=True)
        return None

    fvg = fvg_after(d, side, bos_idx)
    if not fvg:
        print(f"[FILTER IMB] {symbol} {side}", flush=True)
        return None
    fvg_low, fvg_high, fvg_idx = fvg
    entry = float(e[4])
    anchor = float(d[bos_idx][4])
    chase = (entry-anchor)/anchor if side == "LONG" else (anchor-entry)/anchor
    if chase > MAX_CHASE_PCT:
        print(f"[ANTI-CHASE] {symbol} {side} chase={chase*100:.2f}%", flush=True)
        return None
    zone_mid = (fvg_low+fvg_high)/2
    zone_dist = abs(entry-zone_mid)/zone_mid
    if zone_dist > 0.0035:
        print(f"[FILTER IMB DIST] {symbol} {side} dist={zone_dist*100:.2f}%", flush=True)
        return None

    # A 0.50% target is the first quality gate. We also reject setups whose
    # structural invalidation is too close to the target area.
    tp1 = entry*(1+TP1_PCT) if side == "LONG" else entry*(1-TP1_PCT)
    tp2 = entry*(1+TP2_PCT) if side == "LONG" else entry*(1-TP2_PCT)
    if side == "LONG":
        invalid = min(sweep_extreme, poi_low, fvg_low)
        sl = invalid*0.9985
        risk = (entry-sl)/entry
        room = (tp1-entry)/entry
    else:
        invalid = max(sweep_extreme, poi_high, fvg_high)
        sl = invalid*1.0015
        risk = (sl-entry)/entry
        room = (entry-tp1)/entry
    if risk > MAX_RISK_PCT:
        print(f"[FILTER RISK] {symbol} {side} structural_risk={risk*100:.2f}%", flush=True)
        return None
    if room < TP1_PCT:
        print(f"[FILTER ROOM] {symbol} {side} room={room*100:.2f}%", flush=True)
        return None

    key = (symbol, side, round(entry, 8))
    now = time.time()
    if now-last_sent.get(key, 0) < COOLDOWN_SECONDS:
        return None
    last_sent[key] = now

    icon = "🟢" if side == "LONG" else "🔴"
    rsi_now = strict["rsi"]
    rsi_prev = strict["rsi_prev"]
    vol = strict["volume"]
    msg = (
        f"{icon} <b>SMALLFISH STRICT SIGNAL</b>\n\n"
        f"<b>{side} {symbol}</b>\n\n"
        f"Entry: {entry:.8g}\nSL: {sl:.8g}\nTP1: {tp1:.8g}\nTP2: {tp2:.8g}\n\n"
        f"RSI(5m): {rsi_now:.1f} ({rsi_prev:.1f} → {rsi_now:.1f})\n"
        f"OBI: {obi:+.2f}\nVolume: {vol:.2f}x\n"
        f"1H: {h1_ctx} | 15m: {m15_ctx} | 5m: {ctx}\n"
        f"1m confirmation: ✓\n"
        f"Structure: sweep + POI retest + reaction + displacement + BOS + imbalance ✓\n\n"
        f"Target move: ≥0.50%\n\n"
        f"⚠️ Signal-only. No orders are placed."
    )
    print(
        f"[SIGNAL] {symbol} {side} entry={entry:.8g} sl={sl:.8g} "
        f"tp1={tp1:.8g} tp2={tp2:.8g} RSI={rsi_now:.1f} OBI={obi:+.2f} "
        f"VOL={vol:.2f}x risk={risk*100:.2f}%", flush=True
    )
    sent = send(msg)
    if not sent:
        print(f"[SIGNAL WARNING] {symbol} {side} generated but Telegram send failed", flush=True)
    return sent


def heartbeat():
    global last_heartbeat
    now = time.time()
    if now-last_heartbeat >= HEARTBEAT_SECONDS:
        last_heartbeat = now
        print(
            f"[HEARTBEAT] Strict V5.3 alive | symbols={len(SYMBOLS)} | scan={SCAN_SECONDS}s | "
            f"target>=0.50%", flush=True
        )


print("Connecting to MEXC...", flush=True)
try:
    ex.load_markets()
    print(f"MEXC connected. Markets loaded: {len(ex.markets)}", flush=True)
except Exception as e:
    print("[MEXC INIT ERROR]", repr(e), flush=True)
    traceback.print_exc()
    raise

print("=== SCALP BOT V5.3 STRICT-0.50 RUNNING ===", flush=True)
while True:
    cycle_start = time.time()
    for symbol in SYMBOLS:
        try:
            detect(symbol)
        except Exception as e:
            print(f"[DETECT ERROR] {symbol}: {e}", flush=True)
            traceback.print_exc()
    heartbeat()
    elapsed = time.time()-cycle_start
    sleep_for = max(1, SCAN_SECONDS-elapsed)
    print(f"[CYCLE] completed in {elapsed:.1f}s | sleep {sleep_for:.1f}s", flush=True)
    time.sleep(sleep_for)
