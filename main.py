import os
import sqlite3
import logging
import asyncio
import datetime
import yfinance as yf
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# 1. الإعدادات الأساسية
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = 7763725732
CHANNEL_ID = "@StockHunter_AI"

# إعدادات الدفع
USDT_ADDRESS_TRC20 = "TXxxxxxxxxxxxxxxxxxxxxxxxx"
USDT_ADDRESS_BEP20 = "0xYourBEP20Address"
BINANCE_ID = "123456789"
PAYPAL_LINK = "https://paypal.me/yourname"

PRICES = {1: 20, 2: 50, 3: 99}
FREE_LIMIT = 3
TIER1_LIMIT = 20

client = genai.Client(api_key=GEMINI_API_KEY)
DB_FILE = "bot_data.db"

# 2. تهيئة قاعدة البيانات المحسنة
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, usage_count INTEGER DEFAULT 0, tier_level INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS portfolios 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, symbol TEXT, quantity REAL, buy_price REAL, date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS alerts 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, symbol TEXT, condition_type TEXT, target_price REAL, is_triggered INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan INTEGER, status TEXT DEFAULT 'pending')''')
    conn.commit()
    conn.close()

init_db()

# --- دوال التحليل الفني والمالي المحسنة ---

def calculate_rsi_pro(data, window=14):
    """حساب RSI بطريقة Wilder's Smoothing الاحترافية"""
    try:
        if data is None or len(data) < window + 1: return 50.0
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0))
        loss = (-delta.where(delta < 0, 0))
        
        avg_gain = gain.ewm(alpha=1/window, min_periods=window, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/window, min_periods=window, adjust=False).mean()
        
        rs = avg_gain / avg_loss.replace(0, 0.00001)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.dropna().iloc[-1])
    except: return 50.0

# --- وظائف إدارة البيانات ---

def get_user(user_id):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT usage_count, tier_level FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone(); conn.close(); return row

def increment_usage(user_id):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit(); conn.close()

def set_tier_level(user_id, tier=0):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("UPDATE users SET tier_level = ? WHERE user_id = ?", (tier, user_id))
    conn.commit(); conn.close()

# --- إدارة المحفظة الاستثمارية (P&L) ---

def add_to_portfolio(user_id, symbol, quantity, buy_price):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("INSERT INTO portfolios (user_id, symbol, quantity, buy_price) VALUES (?, ?, ?, ?)", 
                   (user_id, symbol.upper(), quantity, buy_price))
    conn.commit(); conn.close()

async def view_portfolio_action(update, context):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT symbol, quantity, buy_price FROM portfolios WHERE user_id = ?", (user_id,))
    stocks = cursor.fetchall(); conn.close()
    
    if not stocks:
        await context.bot.send_message(chat_id=user_id, text="📂 محفظتك فارغة حالياً.")
        return

    report = "📂 **تقرير المحفظة والربح/الخسارة:**\n" + "━"*15 + "\n"
    total_invested = 0.0
    total_current_value = 0.0

    for sym, qty, b_price in stocks:
        ticker = yf.Ticker(sym)
        current_p = ticker.history(period="1d")['Close'].iloc[-1]
        
        cost = qty * b_price
        current_val = qty * current_p
        pnl = current_val - cost
        pnl_pct = (pnl / cost) * 100
        
        total_invested += cost
        total_current_value += current_val
        
        emoji = "🟢" if pnl >= 0 else "🔴"
        report += f"{emoji} `{sym}`: {qty} سهم\n   الربح/الخسارة: {pnl:+.2f}$ ({pnl_pct:+.2f}%)\n"

    total_pnl = total_current_value - total_invested
    report += "━"*15 + f"\n💰 الإجمالي المستثمر: {total_invested:.2f}$\n📈 القيمة الحالية: {total_current_value:.2f}$\n📊 الصافي: {total_pnl:+.2f}$"
    
    await context.bot.send_message(chat_id=user_id, text=report, parse_mode="Markdown")

# --- الأوامر الأساسية ومعالجة الرسائل ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # تسجيل المستخدم إذا لم يكن موجوداً
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, update.effective_user.username))
    conn.commit(); conn.close()

    welcome_text = (
        "🤖 **مرحباً بك في StockHunter AI V12.0**\n"
        "محللك المالي الذكي لإدارة المحافظ وتحليل الأسواق العالمية.\n\n"
        "استخدم الأزرار أدناه للبدء أو الأوامر التالية:\n"
        "• `/risk` - حاسبة المخاطر\n"
        "• `/alert` - تنبيهات الأسعار"
    )
    keyboard = [[InlineKeyboardButton("📊 استعراض الأسواق", callback_data="tier_free")],
                [InlineKeyboardButton("📂 محفظتي", callback_data="port_view")]]
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# --- تنفيذ التحليل المتقدم ---

async def fetch_and_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_symbol=None):
    user_id = update.effective_user.id
    symbol = direct_symbol.upper() if direct_symbol else update.message.text.upper()
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="6mo")
        if df.empty: raise ValueError()

        current_price = df['Close'].iloc[-1]
        rsi = calculate_rsi_pro(df)
        ma50 = df['Close'].rolling(window=50).mean().iloc[-1]
        
        # برومبت احترافي لـ Gemini
        prompt = f"""حلل سهم {symbol} مالياً وفنياً:
        - السعر الحالي: {current_price:.2f}
        - RSI: {rsi:.2f}
        - المتوسط المتحرك 50: {ma50:.2f}
        أعطِ قراراً حاسماً (شراء/بيع/انتظار) مع الأسباب. اللغة: العربية، بدون نجوم."""
        
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        
        report = (
            f"📊 **تحليل الذكاء الاصطناعي لـ {symbol}**\n"
            f"💰 السعر: {current_price:.2f}\n"
            f"📈 RSI: {rsi:.2f}\n"
            f"📉 MA50: {ma50:.2f}\n"
            f"━"*15 + f"\n🤖 **القرار:**\n{response.text}"
        )
        await context.bot.send_message(chat_id=user_id, text=report, parse_mode="Markdown")
        increment_usage(user_id)
    except:
        await context.bot.send_message(chat_id=user_id, text="⚠️ فشل التحليل. تأكد من رمز السهم.")

# --- تشغيل البوت ---

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image_analysis))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fetch_and_analyze))
    
    # تشغيل مجدول التنبيهات
    scheduler = BackgroundScheduler()
    # أضف هنا وظيفة فحص التنبيهات كل دقيقة
    scheduler.start()

    print("🚀 StockHunter AI is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
