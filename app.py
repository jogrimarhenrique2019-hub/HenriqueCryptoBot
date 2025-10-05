from flask import Flask, request, jsonify
import os, requests, sys

app = Flask(__name__)

TOKEN = os.environ["TELEGRAM_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"
SECRET = os.environ.get("WEBHOOK_SECRET", "segredo123")  # opcional via env

@app.route("/")
def home():
    return "HenriqueCryptoBot ativo ✅"

@app.route(f"/webhook/{SECRET}", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "OK", 200  # ajuda a testar no navegador

    data = request.get_json(silent=True) or {}
    print("UPDATE:", data, file=sys.stdout, flush=True)

    msg = data.get("message") or data.get("edited_message")
    if not msg:
        return jsonify(ok=True)

    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")

    reply = "Bot online. Mande qualquer texto." if text.startswith("/start") else f"Você disse: {text}"
    requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": reply})
    return jsonify(ok=True)
