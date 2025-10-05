from flask import Flask, request, jsonify
import os, sys, time, threading, requests, pandas as pd
from binance.spot import Spot as BinanceSpot

app = Flask(__name__)

# --- Telegram ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None
SECRET = os.environ.get("WEBHOOK_SECRET", "segredo123")
OWNER = os.environ.get("ALLOWED_CHAT_ID", "")

def send(chat_id, text):
    if not API: return
    requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text})

# --- Config ---
IS_TESTNET = str(os.environ.get("BINANCE_TESTNET","true")).lower() in ("1","true","yes","y")
BASE_URL = "https://testnet.binance.vision" if IS_TESTNET else "https://api.binance.com"
API_KEY = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")
client = BinanceSpot(api_key=API_KEY, api_secret=API_SECRET, base_url=BASE_URL)

SYMBOL   = os.environ.get("SYMBOL","BTCUSDT")
INTERVAL = os.environ.get("TIMEFRAME","5m")
CAPITAL  = float(os.environ.get("CAPITAL_USDT","1000"))
ORDER_INIT_PCT = float(os.environ.get("ORDER_INIT_PCT","10"))/100.0
DCA_MAX  = int(os.environ.get("DCA_MAX","4"))
DCA_MULT = float(os.environ.get("DCA_MULT","1.5"))
DCA_STEP = float(os.environ.get("DCA_STEP_PCT","1.5"))/100.0
TP       = float(os.environ.get("TP_PCT","4.0"))/100.0
TRAIL    = float(os.environ.get("TRAIL_PCT","0.8"))/100.0
SL       = float(os.environ.get("SL_PCT","2.0"))/100.0
DD_MAX   = float(os.environ.get("DD_MAX_PCT","15"))/100.0
TRADE_ENABLED = str(os.environ.get("TRADE_ENABLED","false")).lower() in ("1","true","yes","y")

# --- Estado mínimo (DRY-RUN) ---
state = {
    "position_qty": 0.0,
    "avg_price": 0.0,
    "dca_count": 0,
    "max_price_since_entry": 0.0,
    "pause_entries": False
}

# --- Indicadores ---
def fetch_klines(limit=600):
    raw = client.klines(SYMBOL, INTERVAL, limit=limit)
    df = pd.DataFrame(raw, columns=["t","open","high","low","close","vol","ct","qv","n","tbb","tbq","i"])
    for c in ["open","high","low","close","vol"]:
        df[c] = df[c].astype(float)
    return df

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, 1e-9)
    return 100 - (100/(1+rs))

def atr(df, n=14):
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def volatility_reduction(df):
    a = atr(df,14); cur = a.iloc[-1]
    tf = INTERVAL
    if tf.endswith("m"): step = int(tf[:-1])
    elif tf.endswith("h"): step = int(tf[:-1])*60
    elif tf.endswith("d"): step = int(tf[:-1])*1440
    else: step = 5
    win = max(50, int((7*1440)/step))
    avg7 = a.iloc[-win:].mean()
    return cur > 2*avg7

def entry_conditions(df):
    close = df["close"].iloc[-1]
    cond1 = close > ema(df["close"],50).iloc[-1]
    cond2 = df["vol"].iloc[-3:].mean() > df["vol"].iloc[-20:].mean()
    cond3 = rsi(df["close"]).iloc[-1] < 60
    return cond1, cond2, cond3

# --- Worker DRY-RUN ---
def worker():
    while True:
        try:
            df = fetch_klines()
            close = df["close"].iloc[-1]
            c1,c2,c3 = entry_conditions(df)
            vol_red = volatility_reduction(df)

            # LOG resumido
            print(f"[{SYMBOL} {INTERVAL}] close={close:.2f} | EMA50={ema(df['close'],50).iloc[-1]:.2f} | "
                  f"vol3>vol20={c2} | RSI<60={c3} | ATR2x7d={vol_red} | pos_qty={state['position_qty']}",
                  flush=True)

            # DRY-RUN: só indica sinal; não envia ordem
            if c1 and c2 and c3 and state["position_qty"]==0 and not state["pause_entries"]:
                size_usdt = CAPITAL*ORDER_INIT_PCT*(0.5 if vol_red else 1.0)
                print(f"==> SINAL DE COMPRA (DRY-RUN) | tamanho ~ {size_usdt:.2f} USDT", flush=True)

            # Saídas (também só log)
            if state["position_qty"]>0:
                ap = state["avg_price"]
                if close >= ap*(1+TP): print("==> TP atingido (DRY-RUN)", flush=True)
                if close <= ap*(1-SL): print("==> STOP LOSS (DRY-RUN)", flush=True)
                if close <= state["max_price_since_entry"]*(1-TRAIL): print("==> TRAILING (DRY-RUN)", flush=True)
                if close < ema(df["close"],50).iloc[-1]: print("==> REVERSÃO EMA50 (DRY-RUN)", flush=True)

        except Exception as e:
            print("WORKER ERR:", e, flush=True)
        time.sleep(10)

# --- Flask básico/Telegram ---
@app.route("/")
def home(): return "HenriqueCryptoBot DRY-RUN ativo"

@app.route(f"/webhook/{SECRET}", methods=["GET","POST"])
def webhook():
    if request.method=="GET": return "OK",200
    data = request.get_json(silent=True) or {}
    msg = data.get("message") or data.get("edited_message")
    if not msg: return jsonify(ok=True)
    chat_id = str(msg["chat"]["id"]); text = (msg.get("text") or "").strip()
    if OWNER and chat_id != str(OWNER): send(chat_id,"Acesso negado."); return jsonify(ok=True)
    if text.startswith("/status"):
        send(chat_id, f"DRY-RUN. Par: {SYMBOL} | TF: {INTERVAL} | trade={'ON' if TRADE_ENABLED else 'OFF'}")
    else:
        send(chat_id, "Comandos: /status")
    return jsonify(ok=True)

threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port)
