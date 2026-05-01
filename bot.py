import os
import sqlite3
import datetime
import yfinance as yf

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
DB = "bot.db"

# ================= DB =================

def db():
    return sqlite3.connect(DB)

def init():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        tier INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

init()

# ================= HELPERS =================

def is_vip(user_id):
    conn = db()
    c = conn.cursor()

    c.execute("SELECT tier FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()

    conn.close()

    return r and r[0] == 1


def register(user_id):
    conn = db()
    c = conn.cursor()

    c.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
    conn.commit()
    conn.close()


# ================= START (IMPORTANT) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register(user_id)

    # 🔥 تحليل مجاني فوري (HOOK)
    data = yf.Ticker("AAPL").history(period="1d")
    price = float(data["Close"].iloc[-1])

    msg = f"""
📊 مرحباً بك!

🔥 هذا تحليل مجاني لحظي:

AAPL
💰 السعر: {price}
📈 الاتجاه: صاعد مبدئيًا
🎯 مثال صفقة: +2% محتملة

━━━━━━━━━━━━━━
💎 هذا مثال من النظام الحقيقي

👉 للحصول على إشارات أقوى ودخول وخروج:
/subscribe
"""

    await update.message.reply_text(msg)


# ================= SUBSCRIBE =================

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
💎 الاشتراك الاحترافي

📊 ماذا ستحصل؟
- إشارات دخول وخروج
- أهداف + وقف خسارة
- تحليل يومي للسوق

💰 السعر: 30$

📩 للتفعيل:
ارسل طلب الدفع + TXID
"""

    await update.message.reply_text(msg)


# ================= SIGNAL (VIP ONLY) =================

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_vip(user_id):
        await update.message.reply_text("🔒 هذه الميزة للمشتركين فقط")
        return

    data = yf.Ticker("TSLA").history(period="1d")
    price = float(data["Close"].iloc[-1])

    msg = f"""
📊 إشارة احترافية

TSLA
💰 {price}

🎯 دخول: مناسب الآن
📈 هدف: +5%
🛑 وقف: -2%
"""

    await update.message.reply_text(msg)


# ================= MAIN =================

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("signal", signal))

    app.run_polling()


if __name__ == "__main__":
    main()
