# Bot Telegram + Binance no Render (webhook + thread de auto)
import os, json, time, threading, hmac, hashlib, urllib.request, urllib.parse
from flask import Flask, request, jsonify

# ====== Config por variáveis de ambiente ======
TOKEN = os.getenv("TELEGRAM_TOKEN", "8288020109:AAESQoa9_dywewZClnMklyQZH1u2a2BjPvM")
BINANCE_KEY = os.getenv("BINANCE_KEY", "b3kuDAaHYRF88O9x0srvYz2w5TB5H0ERckYyYuQDHqQaU31M0XWfNiMobkADvO15")
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "psRsWaleusRZKXlGhDRtvQ4MITwbpOm1zYu0GNwMQuQwPsoSJKQdSzwR6HFVE310")
TESTNET = os.getenv("TESTNET", "true").lower() == "true"
LIVE = os.getenv("LIVE", "false").lower() == "true"

if not TOKEN: raise SystemExit("Falta TELEGRAM_TOKEN")

TG = f"https://api.telegram.org/bot{TOKEN}"
BINANCE = "https://testnet.binance.vision" if TESTNET else "https://api.binance.com"

# ====== Parâmetros ======
SYMBOL = "BTCUSDT"
ORDER_USDT = 25.0
MAX_POS_USDT = 150.0
DROP_PCT = 2.0
TP_PCT = 3.0
SL_PCT = 6.0
POLL_SECONDS = 10

state = {"qty":0.0,"avg":0.0,"peak":0.0,"quote_pos":0.0}
auto_flag = threading.Event()
auto_chat = None

# ====== HTTP helpers ======
def http_get(url, params=None, timeout=15):
    if params: url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())

def tg_post(path, data):
    data = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(TG + path, data=data, timeout=30) as r:
        return json.loads(r.read().decode())

def alert(chat_id, text):
    try: tg_post("/sendMessage", {"chat_id":chat_id, "text":text})
    except Exception as e: print("TG err:", e)

# ====== Binance ======
def price_now():
    d = http_get(BINANCE + "/api/v3/ticker/price", {"symbol": SYMBOL})
    return float(d["price"])

def signed(method, path, params):
    # Só usado em LIVE real (não testnet)
    if not (BINANCE_KEY and BINANCE_SECRET):
        raise RuntimeError("Sem chaves Binance para LIVE.")
    params["timestamp"] = int(time.time()*1000)
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(BINANCE_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(BINANCE + path + "?" + qs + "&signature=" + sig, method=method)
    req.add_header("X-MBX-APIKEY", BINANCE_KEY)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def buy_usdt(usdt):
    if LIVE and not TESTNET:
        o = signed("POST", "/api/v3/order", {"symbol":SYMBOL,"side":"BUY","type":"MARKET","quoteOrderQty":str(usdt)})
        px = float(o.get("fills",[{"price":price_now()}])[0]["price"])
        qty = float(o.get("executedQty", usdt/px))
        return px, qty
    px = price_now()
    return px, usdt/px

def sell_qty(qty):
    if LIVE and not TESTNET:
        o = signed("POST", "/api/v3/order", {"symbol":SYMBOL,"side":"SELL","type":"MARKET","quantity":str(qty)})
        px = float(o.get("fills",[{"price":price_now()}])[0]["price"])
        qf = float(o.get("executedQty", qty))
        return px, qf
    px = price_now()
    return px, qty

# ====== Lógica ======
def fmt_status():
    p = price_now()
    pos = state["qty"]*p
    pnl = (p-state["avg"])/state["avg"]*100 if state["avg"]>0 and state["qty"]>0 else 0.0
    return (f"📊 {SYMBOL}\n📈 Preço: {p:.2f}\n🪙 Qtd: {state['qty']:.8f}\n"
            f"🏷️ Médio: {state['avg']:.2f}\n💼 Posição: {pos:.2f} USDT\n"
            f"📉 PnL: {pnl:.2f}%\n⚙️ LIVE: {'ON' if LIVE else 'OFF'} | TESTNET: {'ON' if TESTNET else 'OFF'}")

def handle(chat_id, text):
    t = (text or "").strip().lower()
    if t == "/start":
        alert(chat_id, "🤖 Bot pronto. Comandos: /preco /comprar 25 /vender 25|all /status /startauto /stopauto"); return
    if t == "/preco":
        alert(chat_id, f"💱 {SYMBOL}: {price_now():.2f}"); return
    if t.startswith("/comprar"):
        try: usdt = float(t.split()[1]) if len(t.split())>1 else ORDER_USDT
        except: alert(chat_id,"Uso: /comprar 25"); return
        px, qty = buy_usdt(usdt)
        new_cost = state["avg"]*state["qty"] + px*qty
        state["qty"] += qty; state["avg"] = new_cost/state["qty"] if state["qty"]>0 else 0.0
        alert(chat_id, f"🟢 Comprado {qty:.8f} @ {px:.2f} ({'REAL' if LIVE and not TESTNET else 'simulado'})"); return
    if t.startswith("/vender"):
        if state["qty"]<=0: alert(chat_id,"Sem posição."); return
        parts = t.split()
        if len(parts)>1 and parts[1]!="all":
            try: qty = min(state["qty"], float(parts[1])/price_now())
            except: alert(chat_id,"Uso: /vender 25 ou /vender all"); return
        else: qty = state["qty"]
        px, qf = sell_qty(qty); state["qty"] -= qf
        if state["qty"]<=1e-12: state["qty"]=0.0; state["avg"]=0.0; state["peak"]=px
        alert(chat_id, f"🟡 Vendido {qf:.8f} @ {px:.2f} ({'REAL' if LIVE and not TESTNET else 'simulado'})"); return
    if t == "/status": alert(chat_id, fmt_status()); return
    if t == "/startauto": start_auto(chat_id); return
    if t == "/stopauto": stop_auto(); alert(chat_id,"⏹️ Auto parado."); return
    alert(chat_id,"❓ Comando desconhecido. Use /start")

def auto_step(chat_id):
    p = price_now()
    if p>state["peak"]: state["peak"]=p
    drop = (state["peak"]-p)/state["peak"]*100 if state["peak"] else 0.0
    if drop>=DROP_PCT and state["qty"]*p<MAX_POS_USDT:
        px, qty = buy_usdt(ORDER_USDT)
        new_cost = state["avg"]*state["qty"] + px*qty
        state["qty"] += qty; state["avg"] = new_cost/state["qty"]
        alert(chat_id, f"🟢 Auto BUY {qty:.8f} @ {px:.2f}")
    if state["qty"]>0:
        pnl = (p-state["avg"])/state["avg"]*100
        if pnl>=TP_PCT:
            ps, _ = sell_qty(state["qty"]); state.update({"qty":0.0,"avg":0.0,"peak":ps})
            alert(chat_id, f"🏁 TAKE-PROFIT +{TP_PCT:.1f}% — vendido @ {ps:.2f}")
        elif pnl<=-SL_PCT:
            ps, _ = sell_qty(state["qty"]); state.update({"qty":0.0,"avg":0.0,"peak":ps})
            alert(chat_id, f"🛑 STOP-LOSS -{SL_PCT:.1f}% — vendido @ {ps:.2f}")

def auto_loop():
    while auto_flag.is_set():
        try: auto_step(auto_chat)
        except Exception as e: print("auto err:", e)
        time.sleep(POLL_SECONDS)

def start_auto(chat_id):
    global auto_chat
    if auto_flag.is_set(): alert(chat_id,"ℹ️ Auto já ativo."); return
    auto_chat = chat_id; auto_flag.set()
    threading.Thread(target=auto_loop, daemon=True).start()
    alert(chat_id, f"▶️ Auto iniciado — DCA {DROP_PCT}% | TP {TP_PCT}% | SL {SL_PCT}%")

def stop_auto(): auto_flag.clear()

# ====== Flask (webhook) ======
app = Flask(__name__)

@app.get("/")
def home(): return "HenriqueCryptoBot OK"

@app.post(f"/webhook/{TOKEN}")
def webhook():
    upd = request.get_json(force=True, silent=True) or {}
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = msg.get("text","")
    if chat_id and text: handle(chat_id, text)
    return jsonify(ok=True)

