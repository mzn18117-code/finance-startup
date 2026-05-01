import os
import sqlite3
import logging
import datetime
import yfinance as yf
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# =========================
# CONFIG
# =========================
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN or not GEMINI_KEY:
    raise Exception("Missing keys")

client = genai.Client(api_key=GEMINI_KEY)

DB = "bot.db"

FREE_LIMIT = 3
PREMIUM_LIMIT = 20

ADMIN_ID = 7763725732

# =========================
# DB
# =========================
def db():
    return sqlite3.connect(DB)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        usage INTEGER DEFAULT 0,
        tier INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        symbol TEXT,
        price REAL,
        triggered INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

init_db()

# =========================
# HELPERS
# =========================
def get_user(uid):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT usage, tier FROM users WHERE user_id=?", (uid,))
    r = c.fetchone()
    conn.close()
    return r

def register(uid, username):
    conn = db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, username))
    conn.commit()
    conn.close()

def inc(uid):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET usage = usage + 1 WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()

def ai(prompt):
    try:
        r = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return r.text
    except:
        return "AI error"

# =========================
# INDICATORS
# =========================
def indicators(df):
    close = df["Close"]

    rsi = 50
    macd = 0

    try:
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi = float(rsi.dropna().iloc[-1])
    except:
        pass

    try:
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        macd = float(macd_line.dropna().iloc[-1])
    except:
        pass

    return rsi, macd

# =========================
# STOCK DATA
# =========================
def get_stock(symbol):
    t = yf.Ticker(symbol)
    h = t.history(period="6mo")
    if h.empty:
        return None

    price = float(h["Close"].iloc[-1])
    ma50 = float(h["Close"].rolling(50).mean().dropna().iloc[-1])
    rsi, macd = indicators(h)

    return price, ma50, rsi, macd

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    register(uid, update.effective_user.username or "user")

    kb = [
        [InlineKeyboardButton("📊 تحليل", callback_data="market")],
        [InlineKeyboardButton("🔔 تنبيه", callback_data="alert")]
    ]

    await update.message.reply_text("🤖 PRO MAX BOT", reply_markup=InlineKeyboardMarkup(kb))

# =========================
# BUTTONS
# =========================
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "market":
        kb = [
            [InlineKeyboardButton("AAPL", callback_data="AAPL")],
            [InlineKeyboardButton("TSLA", callback_data="TSLA")],
            [InlineKeyboardButton("BTC", callback_data="BTC-USD")]
        ]
        await q.edit_message_text("اختر:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "alert":
        await q.edit_message_text("أرسل: symbol price\nمثال: AAPL 180")

    else:
        await analyze(q, q.from_user.id, q.data)

# =========================
# ANALYSIS
# =========================
async def analyze(q, uid, symbol):
    register(uid, "user")

    user = get_user(uid)
    usage = user[0] if user else 0
    tier = user[1] if user else 0

    limit = FREE_LIMIT if tier == 0 else PREMIUM_LIMIT

    if usage >= limit:
        await q.edit_message_text("❌ limit reached")
        return

    data = get_stock(symbol)
    if not data:
        await q.edit_message_text("no data")
        return

    price, ma50, rsi, macd = data

    inc(uid)

    decision = "HOLD"
    if rsi < 30 and macd > 0:
        decision = "BUY"
    elif rsi > 70:
        decision = "SELL"

    prompt = f"""
Stock: {symbol}
Price: {price}
RSI: {rsi}
MACD: {macd}
Decision: {decision}
Explain briefly in Arabic.
"""

    ai_text = ai(prompt)

    msg = f"""
📊 {symbol}

Price: {price}
RSI: {rsi:.2f}
MACD: {macd:.2f}

🤖 Decision: {decision}

{ai_text}
"""

    await q.edit_message_text(msg)

# =========================
# TEXT INPUT
# =========================
async def text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        symbol = parts[0].upper()
        price = float(parts[1])

        conn = db()
        c = conn.cursor()
        c.execute("INSERT INTO alerts (user_id, symbol, price) VALUES (?,?,?)",
                  (update.effective_user.id, symbol, price))
        conn.commit()
        conn.close()

        await update.message.reply_text("✅ alert set")

    except:
        await update.message.reply_text("format: SYMBOL PRICE")

# =========================
# ALERT CHECKER
# =========================
async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, user_id, symbol, price FROM alerts WHERE triggered=0")
    alerts = c.fetchall()

    for aid, uid, sym, target in alerts:
        try:
            price = yf.Ticker(sym).history(period="1d")["Close"].iloc[-1]

            if price >= target:
                await context.bot.send_message(uid, f"🚨 {sym} reached {price}")
                c.execute("UPDATE alerts SET triggered=1 WHERE id=?", (aid,))
        except:
            pass

    conn.commit()
    conn.close()

# =========================
# MAIN
# =========================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))

    app.job_queue.run_repeating(check_alerts, interval=300)

    print("RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
