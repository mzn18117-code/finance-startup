import os
import sqlite3
import datetime
import asyncio
import logging
import uuid

from http.server import HTTPServer, BaseHTTPRequestHandler

import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
DB = "data.db"

# ================= DB =================

def db():
    return sqlite3.connect(DB)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        tier INTEGER DEFAULT 0,
        expiry TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        order_id TEXT,
        txid TEXT,
        status TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS referrals(
        referrer_id INTEGER,
        referred_id INTEGER,
        commission REAL DEFAULT 0
    )""")

    conn.commit()
    conn.close()

init_db()

# ================= Utils =================

def is_active(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT expiry FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    if not r or not r[0]:
        return False
    return datetime.datetime.utcnow() < datetime.datetime.fromisoformat(r[0])

def create_payment(user_id, amount):
    order = str(uuid.uuid4())[:8]
    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO payments(user_id,order_id,status) VALUES(?,?,?)",
              (user_id, order, "pending"))
    conn.commit()
    conn.close()
    return order

# ================= Commands =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    conn = db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
    conn.commit()

    # referral
    if context.args:
        if context.args[0].startswith("ref_"):
            ref = int(context.args[0].split("_")[1])
            if ref != user_id:
                c.execute("INSERT INTO referrals VALUES(?,?,0)", (ref, user_id))
                conn.commit()

    conn.close()

    await update.message.reply_text(
        "🤖 أهلاً بك\n"
        "جرب البوت أو اشترك:\n"
        "/subscribe\n"
        "/ref"
    )

# ---------- Subscribe ----------

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order = create_payment(user_id, 30)

    await update.message.reply_text(f"""
💎 الاشتراك

💰 30 USDT

🆔 {order}

💳 TRC20:
YOUR_WALLET

بعد الدفع:
/verify {order} TXID
""")

# ---------- Verify ----------

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if len(context.args) < 2:
        return await update.message.reply_text("خطأ")

    order, txid = context.args

    conn = db()
    c = conn.cursor()
    c.execute("UPDATE payments SET txid=?,status='review' WHERE order_id=?",
              (txid, order))
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅", callback_data=f"ok_{user_id}"),
        InlineKeyboardButton("❌", callback_data=f"no_{user_id}")
    ]])

    await context.bot.send_message(
        ADMIN_ID,
        f"طلب:\n{user_id}\n{order}\n{txid}",
        reply_markup=kb
    )

    await update.message.reply_text("⏳ تم الإرسال")

# ---------- Admin ----------

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data

    if data.startswith("ok_"):
        user = int(data.split("_")[1])

        expiry = datetime.datetime.utcnow() + datetime.timedelta(days=30)

        conn = db()
        c = conn.cursor()

        c.execute("UPDATE users SET tier=3,expiry=? WHERE user_id=?",
                  (expiry.isoformat(), user))

        c.execute("UPDATE payments SET status='ok' WHERE user_id=?", (user,))

        # referral commission
        c.execute("SELECT referrer_id FROM referrals WHERE referred_id=?", (user,))
        r = c.fetchone()
        if r:
            c.execute("UPDATE referrals SET commission=commission+6 WHERE referred_id=?", (user,))

        conn.commit()
        conn.close()

        await context.bot.send_message(user, "🎉 تم التفعيل")
        await q.answer("تم")

# ---------- Referral ----------

async def ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{update.effective_user.id}"

    await update.message.reply_text(f"🔗 رابطك:\n{link}")

async def earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT SUM(commission) FROM referrals WHERE referrer_id=?",
              (update.effective_user.id,))
    total = c.fetchone()[0] or 0
    conn.close()

    await update.message.reply_text(f"💰 أرباحك: {total}$")

# ---------- Signals ----------

async def signal(context: ContextTypes.DEFAULT_TYPE):
    users = db().cursor().execute("SELECT user_id FROM users").fetchall()

    price = yf.Ticker("AAPL").history(period="1d")['Close'].iloc[-1]

    for (u,) in users:
        if is_active(u):
            try:
                await context.bot.send_message(u, f"📊 AAPL\n💰 {price}")
            except:
                pass

# ================= Web (Render) =================

class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

# ================= MAIN =================

async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("ref", ref))
    app.add_handler(CommandHandler("earnings", earnings))
    app.add_handler(CallbackQueryHandler(admin))

    app.job_queue.run_repeating(signal, interval=86400)

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Ping)

    while True:
        server.handle_request()
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
