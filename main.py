import os
import sqlite3
import logging
import asyncio
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# 1. إعدادات التسجيل والمفاتيح
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

# أسعار الباقات
PRICES = {
    1: 20,
    2: 50,
    3: 99
}

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("⚠️ تأكد من إدخال TELEGRAM_TOKEN و GEMINI_API_KEY في متغيرات البيئة!")

client = genai.Client(api_key=GEMINI_API_KEY)
DB_FILE = "bot_data.db"

FREE_LIMIT = 3
TIER1_LIMIT = 20

# 2. تهيئة قاعدة البيانات SQLite
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            usage_count INTEGER DEFAULT 0,
            tier_level INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            quantity REAL,
            buy_price REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            condition_type TEXT,
            target_price REAL,
            is_triggered INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN tier_level INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass 
    conn.commit()
    conn.close()

init_db()

# دوال الاشتراكات وإدارة البيانات
def get_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT usage_count, tier_level FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def register_or_update_user(user_id, username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO users (user_id, username, usage_count, tier_level) VALUES (?, ?, 0, 0)", (user_id, username))
    conn.commit()
    conn.close()

def increment_usage(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def set_tier_level(user_id, tier=0):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET tier_level = ? WHERE user_id = ?", (tier, user_id))
    conn.commit()
    conn.close()

def reset_daily_usage():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET usage_count = 0 WHERE tier_level < 2")
        conn.commit()
        conn.close()
        logging.info("🔄 تم تصفير عداد الاستخدام اليومي بنجاح.")
    except Exception as e:
        logging.error(f"Error resetting daily usage: {e}")

def create_subscription(user_id, plan):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO subscriptions (user_id, plan, status) VALUES (?, ?, 'pending')", (user_id, plan))
    conn.commit()
    conn.close()

def get_pending_subscriptions():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, plan FROM subscriptions WHERE status='pending'")
    rows = cursor.fetchall()
    conn.close()
    return rows

def approve_subscription(sub_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE subscriptions SET status='approved' WHERE id=?", (sub_id,))
    conn.commit()
    conn.close()

# دوال إدارة المحفظة والتنبيهات
def add_to_portfolio(user_id, symbol, quantity, buy_price):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO portfolios (user_id, symbol, quantity, buy_price) VALUES (?, ?, ?, ?)", 
                   (user_id, symbol.upper(), quantity, buy_price))
    conn.commit()
    conn.close()

def get_portfolio(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, quantity, buy_price FROM portfolios WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def clear_portfolio(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolios WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_alert(user_id, symbol, condition_type, target_price):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO alerts (user_id, symbol, condition_type, target_price, is_triggered) VALUES (?, ?, ?, ?, 0)", 
                   (user_id, symbol.upper(), condition_type, target_price))
    conn.commit()
    conn.close()

def get_active_alerts():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, symbol, condition_type, target_price FROM alerts WHERE is_triggered = 0")
    rows = cursor.fetchall()
    conn.close()
    return rows

def mark_alert_triggered(alert_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE alerts SET is_triggered = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()

# وظيفة الخلفية لفحص التنبيهات
async def check_alerts_job(context: ContextTypes.DEFAULT_TYPE):
    alerts = get_active_alerts()
    for alert_id, user_id, symbol, cond, target in alerts:
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="1d")
            if history.empty:
                continue
            current_p = float(history['Close'].dropna().iloc[-1])
            triggered = False
            if cond == ">" and current_p >= target:
                triggered = True
            elif cond == "<" and current_p <= target:
                triggered = True
            if triggered:
                mark_alert_triggered(alert_id)
                msg = (
                    f"🚨 **تنبيه السعر الذكي!**\n"
                    f"الأصل: `{symbol}` قد حقق شرطك الآن!\n"
                    f"السعر الحالي: `{current_p:.2f}` (الشرط: {cond} {target})"
                )
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Error checking alert {alert_id}: {e}")

def calculate_rsi(data, window=14):
    try:
        if data is None or len(data) < window or 'Close' not in data:
            return 50.0
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        loss = loss.apply(lambda x: 0.00001 if x == 0 else x)
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.dropna().iloc[-1])
    except Exception as e:
        logging.error(f"Error in RSI: {e}")
        return 50.0

user_context = {}

class PingServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("البوت يعمل بنجاح 🚀".encode("utf-8"))
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

# النشر التلقائي في القناة
async def auto_post_to_channel(context: ContextTypes.DEFAULT_TYPE):
    symbol = "NVDA"
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo")
        if history is None or history.empty:
            return

        current_price = float(history['Close'].dropna().iloc[-1])
        rsi_value = calculate_rsi(history)
        ma_50 = float(history['Close'].rolling(window=min(len(history), 50)).mean().dropna().iloc[-1])

        prompt = f"حلل {symbol}: السعر {current_price}, RSI {rsi_value}, MA50 {ma_50}. اعط قراراً باللغة العربية دون استخدام النجوم تماماً."
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        ai_text = response.text if response and hasattr(response, 'text') else "تعذر جلب التحليل."

        channel_msg = (
            f"📢 **تقرير البوت اليومي المجاني**\n"
            f"🔍 **الأصل المختار:** {symbol}\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **السعر الحالي:** {current_price:.2f}\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 **تحليل الذكاء الاصطناعي:**\n\n{ai_text}\n"
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=channel_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error auto post: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    register_or_update_user(user_id, username)
    if user_id not in user_context:
        user_context[user_id] = {}
    
    welcome_msg = (
        "🤖 **مرحباً بك في StockHunter AI V11.0** 📈\n"
        "**منصتك الاحترافية للتحليل، إدارة المخاطر، والتنبيهات اللحظية**\n\n"
        "👑 **توزيع الميزات والصلاحيات المتاحة:**\n"
        "• **🆓 المجانية:** تحليل فني أساسي للسوق الأمريكي فقط (3 يومياً).\n"
        "• **💎 الأساسية ($20):** الأمريكي والخليجي (فني + مالي) (20 يومياً).\n"
        "• **🔥 المتقدمة ($50):** كل ما سبق + السلع والذهب + التنبيهات الذكية + حاسبة المخاطر.\n"
        "• **👑 باقة VIP ($99):** كافة الأسواق والمؤشرات + القرار الحاسِم المباشر + قراءة صور الشارتات.\n\n"
        "👇 **يرجى اختيار وجهتك من الأزرار أدناه:**"
    )
    keyboard = [
        [InlineKeyboardButton("🏁 استعراض الأسواق والخدمات", callback_data="tier_free")],
        [InlineKeyboardButton("💎 باقات الاشتراك المميز", callback_data="tier_premium_info")]
    ]
    await (update.message.reply_text(welcome_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown") if update.message 
           else update.callback_query.message.reply_text(welcome_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id not in user_context:
        user_context[user_id] = {}

    user_data = get_user(user_id)
    tier_level = user_data[1] if user_data else 0

    if data == "tier_free":
        msg = "🎯 **الرجاء اختيار السوق أو السلعة التي ترغب بتحليلها:**"
        keyboard = [
            [InlineKeyboardButton("🇺🇸 السوق الأمريكي", callback_data="mkt_us")],
            [InlineKeyboardButton("🇸🇦 السوق السعودي والخليجي" if tier_level >= 1 else "🔒 السوق الخليجي (باقة $20)", callback_data="mkt_gulf" if tier_level >= 1 else "alert_tier1")],
            [InlineKeyboardButton("📀 الذهب، النفط، والسلع" if tier_level >= 2 else "🔒 الذهب والسلع (باقة $50)", callback_data="mkt_commodities" if tier_level >= 2 else "alert_tier2")],
            [InlineKeyboardButton("📈 المؤشرات والعملات الرقمية" if tier_level >= 3 else "🔒 المؤشرات والعملات الرقمية (VIP)", callback_data="mkt_global_crypto" if tier_level >= 3 else "alert_tier3")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("alert_tier"):
        req = data.replace("alert_tier", "")
        names = {"1": "الباقة الأساسية ($20)", "2": "الباقة المتقدمة ($50)", "3": "باقة VIP ($99)"}
        await query.edit_message_text(f"🔒 **هذا السوق مخصص لـ {names.get(req)}.**", 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 خطط الاشتراك", callback_data="tier_premium_info"), InlineKeyboardButton("🔙 العودة", callback_data="tier_free")]]), parse_mode="Markdown")

    elif data == "tier_premium_info":
        keyboard = [
            [InlineKeyboardButton("💎 $20 - الباقة الأساسية", callback_data="buy_1")],
            [InlineKeyboardButton("🔥 $50 - الباقة المتقدمة", callback_data="buy_2")],
            [InlineKeyboardButton("👑 $99 - VIP", callback_data="buy_3")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
        ]
        await query.edit_message_text("💳 اختر الباقة للدفع:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("buy_"):
        tier = int(data.split("_")[1])
        price = PRICES.get(tier, 0)
        keyboard = [
            [InlineKeyboardButton("💰 USDT", callback_data=f"pay_usdt_{tier}")],
            [InlineKeyboardButton("🟡 Binance", callback_data=f"pay_binance_{tier}")],
            [InlineKeyboardButton("💳 PayPal", callback_data=f"pay_paypal_{tier}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="tier_premium_info")]
        ]
        await query.edit_message_text(
            f"💳 اختر طريقة الدفع\n\nالباقة: {tier}\nالسعر: ${price}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("pay_usdt_"):
        tier = int(data.split("_")[2])
        price = PRICES[tier]
        msg = f"""
💰 الدفع عبر USDT

المبلغ: {price}$

TRC20:
`{USDT_ADDRESS_TRC20}`

BEP20:
`{USDT_ADDRESS_BEP20}`

📸 بعد الدفع أرسل صورة التحويل هنا
وسيتم التفعيل خلال دقائق.
"""
        user_context[user_id]["payment_tier"] = tier
        user_context[user_id]["state"] = "WAITING_PAYMENT_PROOF"
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data.startswith("pay_binance_"):
        tier = int(data.split("_")[2])
        price = PRICES[tier]
        msg = f"""
🟡 الدفع عبر Binance

ID:
`{BINANCE_ID}`

المبلغ: {price}$

📸 أرسل إثبات التحويل (صورة)
"""
        user_context[user_id]["payment_tier"] = tier
        user_context[user_id]["state"] = "WAITING_PAYMENT_PROOF"
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data.startswith("pay_paypal_"):
        tier = int(data.split("_")[2])
        price = PRICES[tier]
        msg = f"""
💳 الدفع عبر PayPal

الرابط:
{PAYPAL_LINK}

المبلغ: {price}$

📸 بعد الدفع أرسل صورة
"""
        user_context[user_id]["payment_tier"] = tier
        user_context[user_id]["state"] = "WAITING_PAYMENT_PROOF"
        await query.edit_message_text(msg)

    elif data.startswith("sub_"):
        plan = int(data.replace("sub_", ""))
        create_subscription(user_id, plan)
        await query.edit_message_text(
            "✅ تم إرسال طلب اشتراكك بنجاح!\n"
            "📩 سيتم مراجعته وتفعيله من الإدارة خلال وقت قصير."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ موافقة", callback_data=f"approve_{user_id}_{plan}")]
        ])
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📥 طلب اشتراك جديد\n\n👤 ID: `{user_id}`\n📦 الباقة: {plan}",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    elif data.startswith("approve_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_id = int(parts[1])
        plan = int(parts[2])
        set_tier_level(target_id, plan)
        await query.edit_message_text("✅ تم تفعيل الاشتراك")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🎉 تم تفعيل اشتراكك بنجاح في المستوى: {plan}!"
            )
        except:
            pass

    elif data == "back_home":
        await start(update, context)

    elif data.startswith("mkt_"):
        market_type = data.replace("mkt_", "").upper()
        user_context[user_id]["market"] = market_type
        
        msg = "💡 **اختر الخدمة المطلوبة:**"
        keyboard = [
            [InlineKeyboardButton("📊 تحليل فني ومؤشرات السعر", callback_data="srv_tech")],
            [InlineKeyboardButton("🔬 تحليل مالي وفني عميق وقرار الـ AI", callback_data="srv_deep")]
        ]
        if tier_level >= 2:
            keyboard.append([InlineKeyboardButton("📂 المحفظة الاستثمارية", callback_data="port_view")])
            keyboard.append([InlineKeyboardButton("➕ إضافة للمحفظة", callback_data="port_add")])
        if tier_level >= 3:
            keyboard.append([InlineKeyboardButton("🖼️ تحليل صورة شارت (Visual AI)", callback_data="visual_ai_prompt")])
            
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("srv_"):
        srv_type = "TECH" if data == "srv_tech" else "DEEP"
        user_context[user_id]["service"] = srv_type
        
        market = user_context.get(user_id, {}).get("market")
        if market == "US":
            keyboard = [[InlineKeyboardButton("🍏 AAPL", callback_data="sym_AAPL"), InlineKeyboardButton("🚗 TSLA", callback_data="sym_TSLA")],
                        [InlineKeyboardButton("🎮 NVDA", callback_data="sym_NVDA"), InlineKeyboardButton("✍️ إرسال رمز آخر", callback_data="sym_manual")]]
        elif market == "GULF":
            keyboard = [[InlineKeyboardButton("🛢️ أرامكو (2222.SR)", callback_data="sym_2222.SR"), InlineKeyboardButton("🏦 الراجحي (1120.SR)", callback_data="sym_1120.SR")],
                        [InlineKeyboardButton("✍️ إرسال رمز آخر", callback_data="sym_manual")]]
        elif market == "COMMODITIES":
            keyboard = [[InlineKeyboardButton("📀 الذهب", callback_data="sym_GC=F"), InlineKeyboardButton("🛢️ النفط الخام", callback_data="sym_CL=F")],
                        [InlineKeyboardButton("✍️ إرسال رمز آخر", callback_data="sym_manual")]]
        else:
            keyboard = [[InlineKeyboardButton("🪙 بيتكوين", callback_data="sym_BTC-USD"), InlineKeyboardButton("📊 مؤشر S&P 500", callback_data="sym_^GSPC")],
                        [InlineKeyboardButton("✍️ إرسال رمز آخر", callback_data="sym_manual")]]
            
        await query.edit_message_text("⌨️ اختر الرمز أو اكتبه يدوياً:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("sym_"):
        symbol = data.replace("sym_", "")
        if symbol == "manual":
            await query.edit_message_text("⌨️ **أرسل الرمز الآن مباشرة في الشات (مثل: MSFT):**", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"⏳ جاري تحليل `{symbol}`...")
            await fetch_and_analyze(update, context, direct_symbol=symbol)

    elif data == "port_view" and tier_level >= 2:
        await view_portfolio_action(update, context)
        
    elif data == "port_add" and tier_level >= 2:
        user_context[user_id]["state"] = "AWAITING_PORTFOLIO_DATA"
        await query.edit_message_text("➕ أرسل البيانات بالصيغة التالية:\n`رمز الأصل, الكمية, سعر الشراء`", parse_mode="Markdown")

    elif data == "visual_ai_prompt" and tier_level >= 3:
        user_context[user_id]["state"] = "AWAITING_CHART_IMAGE"
        await query.edit_message_text("🖼️ **يرجى إرسال أو رفع صورة الشارت الآن مباشرة، وسيقوم الـ AI بقراءتها وتحليلها فوراً.**", parse_mode="Markdown")

    elif data == "adm_list_premium" and user_id == ADMIN_ID:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, tier_level FROM users WHERE tier_level > 0")
        premium_users = cursor.fetchall()
        conn.close()
        if not premium_users:
            await query.message.reply_text("ℹ️ لا يوجد مشتركين مدفوعين.")
            return
        list_msg = "💎 **المشتركون المدفوعون:**\n"
        for u_id, username, tier in premium_users:
            list_msg += f"👤 `@{username}` | ID: `{u_id}` | الباقة: **{tier}**\n"
        await query.message.reply_text(list_msg, parse_mode="Markdown")

    elif data == "adm_reset_usage" and user_id == ADMIN_ID:
        reset_daily_usage()
        await query.message.reply_text("✅ تم تصفير العداد لجميع المستخدمين.")

async def view_portfolio_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stocks = get_portfolio(user_id)
    if not stocks:
        await context.bot.send_message(chat_id=user_id, text="📂 محفظتك فارغة حالياً.", parse_mode="Markdown")
        return
    report = "📂 **تقرير محفظتك الاستثمارية:**\n━━━━━━━━━━━━━━━━━━━\n"
    total_cost = total_value = 0.0
    for symbol, qty, buy_p in stocks:
        try:
            h = yf.Ticker(symbol).history(period="1d")
            current_p = float(h['Close'].dropna().iloc[-1]) if not h.empty else buy_p
        except:
            current_p = buy_p
        cost = qty * buy_p
        val = qty * current_p
        total_cost += cost
        total_value += val
        report += f"📌 `{symbol}` | الكمية: {qty} | الشراء: {buy_p:.2f} | الحالي: {current_p:.2f} | الأداء: {val-cost:+.2f} ({((val-cost)/cost)*100:+.2f}%)\n"
    
    total_pl = total_value - total_cost
    report += f"━━━━━━━━━━━━━━━━━━━\n💰 التكلفة الإجمالية: {total_cost:.2f} | القيمة الحالية: {total_value:.2f}\n📊 صافي الأداء: {total_pl:+.2f} ({((total_pl)/total_cost)*100 if total_cost>0 else 0:+.2f}%)"
    await context.bot.send_message(chat_id=user_id, text=report, parse_mode="Markdown")

# أوامر التنبيه الذكي وإدارة المخاطر
async def create_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or user_data[1] < 2:
        await update.message.reply_text("🔒 ميزة التنبيهات متاحة ابتداءً من الباقة المتقدمة ($50).")
        return
    if len(context.args) < 3:
        await update.message.reply_text("⚠️ استخدام خاطئ. مثال:\n`/alert AAPL > 185` أو `/alert GC=F < 2150`")
        return
    try:
        symbol = context.args[0].upper().strip()
        condition = context.args[1].strip()
        price = float(context.args[2].strip())
        if condition not in [">", "<"]:
            await update.message.reply_text("❌ شرط خاطئ. استخدم `>` أو `<` فقط.")
            return
        add_alert(user_id, symbol, condition, price)
        await update.message.reply_text(f"✅ تم تفعيل التنبيه لـ `{symbol}` عندما يصبح السعر {condition} `{price}`.")
    except ValueError:
        await update.message.reply_text("⚠️ خطأ في كتابة الأرقام.")

async def risk_calculator_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or user_data[1] < 2:
        await update.message.reply_text("🔒 ميزة حاسبة المخاطر متاحة ابتداءً من الباقة المتقدمة ($50).")
        return
    if len(context.args) < 4:
        await update.message.reply_text("⚠️ مثال:\n`/risk [رأس_المال] [الرمز] [سعر_الدخول] [سعر_وقف_الخسارة]`\nمثال: `/risk 10000 AAPL 170 160`")
        return
    try:
        balance = float(context.args[0])
        symbol = context.args[1].upper()
        entry = float(context.args[2])
        stop = float(context.args[3])
        
        if entry == stop:
            await update.message.reply_text("❌ لا يمكن أن يكون سعر الدخول مساوياً لوقف الخسارة.")
            return
            
        risk_amount = balance * 0.02 # نسبة المخاطرة القياسية 2%
        loss_per_share = abs(entry - stop)
        shares_to_buy = risk_amount / loss_per_share
        total_cost = shares_to_buy * entry
        
        msg = (
            f"📊 **تقرير إدارة المخاطر لـ:** `{symbol}`\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"💰 الحد الأقصى للمخاطرة (2%): `{risk_amount:.2f}`\n"
            f"📉 الخسارة لكل سهم: `{loss_per_share:.2f}`\n\n"
            f"🛒 **الكمية الموصى بشرائها:** `{int(shares_to_buy)} سهم`\n"
            f"💵 إجمالي قيمة الصفقة: `{total_cost:.2f}`\n"
            f"⚠️ التزم بوقف الخسارة الصارم عند: `{stop}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ خطأ في المدخلات. تأكد من إدخال أرقام صحيحة.")

# معالجة الصور (Visual AI) للـ VIP
async def handle_image_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or user_data[1] < 3:
        await update.message.reply_text("🔒 ميزة قراءة وتحليل الشارتات متاحة حصرياً للمشتركين VIP.")
        return
    
    if user_id in user_context and user_context[user_id].get("state") == "AWAITING_CHART_IMAGE":
        user_context[user_id]["state"] = None
        loading_msg = await update.message.reply_text("⏳ يقوم الـ AI بفحص وقراءة صورة الشارت الآن...")
        try:
            photo_file = await update.message.photo[-1].get_file()
            img_bytes = await photo_file.download_as_bytearray()
            
            prompt = "أنت خبير مالي ومحلل شارتات محترف. اقرأ الصورة المرفقة واستخرج الدعوم والمقاومات والنماذج الفنية المتكونة. اعط قراراً باللغة العربية دون استخدام النجوم."
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    {"mime_type": "image/jpeg", "data": bytes(img_bytes)},
                    prompt
                ]
            )
            ai_text = response.text if response and hasattr(response, 'text') else "تعذر تحليل الشارت المرفق حالياً."
            await context.bot.delete_message(chat_id=user_id, message_id=loading_msg.message_id)
            await update.message.reply_text(f"🖼️ **التقرير الفني البصري للـ AI:**\n\n{ai_text}", parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Visual AI Error: {e}")
            await update.message.reply_text("⚠️ حدث خطأ أثناء معالجة وقراءة الصورة.")

# استقبال إثباتات الدفع بالصور
async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_context and user_context[user_id].get("state") == "WAITING_PAYMENT_PROOF":
        tier = user_context[user_id].get("payment_tier")
        photo = await update.message.photo[-1].get_file()
        file = await photo.download_as_bytearray()
        
        create_subscription(user_id, tier)
        
        caption = f"💰 **إثبات دفع جديد**\n\n👤 User ID: `{user_id}`\n📦 Tier: `{tier}`"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ موافقة وتفعيل", callback_data=f"approve_{user_id}_{tier}")]
        ])
        
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await update.message.reply_text("✅ تم إرسال الإثبات بنجاح، انتظر التفعيل والمراجعة من الإدارة.")
        user_context[user_id]["state"] = None
        return True
    return False

async def fetch_and_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_symbol=None):
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    register_or_update_user(user_id, username)
    user_data = get_user(user_id)
    usage_count, tier_level = user_data[0], user_data[1]

    if tier_level == 0 and usage_count >= FREE_LIMIT:
        await context.bot.send_message(chat_id=user_id, text="🔒 انتهت المحاولات المجانية اليوم (3).", parse_mode="Markdown")
        return
    elif tier_level == 1 and usage_count >= TIER1_LIMIT:
        await context.bot.send_message(chat_id=user_id, text="🔒 انتهت محاولاتك لليوم (20).", parse_mode="Markdown")
        return

    if user_id in user_context and user_context[user_id].get("state") == "AWAITING_PORTFOLIO_DATA" and not direct_symbol:
        try:
            parts = update.message.text.split(",")
            symbol = parts[0].strip().upper()
            qty = float(parts[1].strip())
            buy_price = float(parts[2].strip())
            add_to_portfolio(user_id, symbol, qty, buy_price)
            user_context[user_id]["state"] = None
            await update.message.reply_text(f"✅ تم إضافة `{symbol}` للمحفظة بنجاح.")
            return
        except Exception:
            await update.message.reply_text("⚠️ خطأ في الصيغة. استخدم:\n`رمز, كمية, سعر`")
            return

    if user_id not in user_context or "market" not in user_context[user_id] or "service" not in user_context[user_id]:
        await context.bot.send_message(chat_id=user_id, text="الرجاء البدء بالضغط على /start أولاً.")
        return

    symbol = direct_symbol.upper().strip() if direct_symbol else update.message.text.upper().strip()
    loading_msg = await context.bot.send_message(chat_id=user_id, text=f"⏳ جاري التحليل الاحترافي لـ {symbol}...")
    
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo")
        if history is None or history.empty:
            await context.bot.send_message(chat_id=user_id, text=f"❌ لم نجد بيانات لـ `{symbol}`.")
            return

        current_price = float(history['Close'].dropna().iloc[-1])
        rsi_value = calculate_rsi(history)
        ma_50 = float(history['Close'].rolling(window=min(len(history), 50)).mean().dropna().iloc[-1])
        
        user_srv = user_context[user_id]["service"]
        if tier_level < 2:
            increment_usage(user_id)
            remaining = (FREE_LIMIT if tier_level == 0 else TIER1_LIMIT) - (usage_count + 1)
        else:
            remaining = "مفتوح (VIP 👑)"

        if user_srv == "TECH":
            status = "تشبع بيعي" if rsi_value < 35 else "تشبع شرائي" if rsi_value > 65 else "حياد واستقرار"
            trend = "صاعد (Bullish)" if current_price > ma_50 else "هابط (Bearish)"
            tech_report = (
                f"📊 **التقرير الفني لـ:** {symbol}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **السعر الحالي:** {current_price:.2f}\n"
                f"📉 **مؤشر RSI:** {rsi_value:.2f} ({status})\n"
                f"📈 **الاتجاه العام:** {trend}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 الاستخدام المتبقي: {remaining}"
            )
            await context.bot.delete_message(chat_id=user_id, message_id=loading_msg.message_id)
            await context.bot.send_message(chat_id=user_id, text=tech_report, parse_mode="Markdown")

        elif user_srv == "DEEP":
            if tier_level == 0:
                await context.bot.send_message(chat_id=user_id, text="⚠️ هذه الميزة للمشتركين Premium فقط.")
                return
            pe_ratio = eps = "غير متوفر"
            div_yield = 0.0
            try:
                info = ticker.info
                if isinstance(info, dict):
                    pe_ratio = info.get('trailingPE', 'غير متوفر')
                    eps = info.get('trailingEps', 'غير متوفر')
                    raw_yield = info.get('dividendYield', 0)
                    if raw_yield and 0 < raw_yield < 0.5:
                        div_yield = raw_yield * 100
            except:
                pass

            if tier_level == 3:
                prompt = f"""
                أنت خبير مالي ومحلل مخاطر أول للصفقات الكبرى (VIP). حلل {symbol}:
                السعر: {current_price:.2f}, مكرر الربحية: {pe_ratio}, ربحية السهم: {eps}, العائد: {div_yield:.2f}%, RSI {rsi_value:.2f}, MA50 {ma_50:.2f}.
                
                شروط صارمة للإجابة (تجنب النجوم تماماً):
                1. ممنوع نهائياً استخدام خيار (مراقبة) أو (حياد). يجب اتخاذ قرار حاسم: إما (شراء) أو (بيع).
                2. ابدأ التقرير بملخص تنفيذي من سطرين يوضح القرار مباشرة.
                3. اذكر الأسباب الفنية والمالية باختصار.
                4. اذكر خطة التداول المباشرة: (الدخول، الهدف الأول، الهدف الثاني، وقف الخسارة الصارم).
                """
            else:
                prompt = f"""
                أنت مستشار مالي معتمد. حلل {symbol}:
                السعر: {current_price:.2f}, مكرر الربحية: {pe_ratio}, ربحية السهم: {eps}, العائد: {div_yield:.2f}%, RSI {rsi_value:.2f}, MA50 {ma_50:.2f}.
                اكتب التقرير باللغة العربية كالتالي دون نجوم تماماً:
                1. القرار النهائي (شراء أو مراقبة أو بيع).
                2. الأسباب المالية والفنية باختصار.
                3. خطة التداول: (الدخول، الهدف، وقف الخسارة).
                """
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            ai_text = response.text if response and hasattr(response, 'text') else "تعذر التحليل الذكي."
            tier_name = "VIP 👑" if tier_level == 3 else "Premium 💎"
            
            deep_report = (
                f"📊 **تقرير المشتركين {tier_name} لـ:** {symbol}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **السعر الحالي:** {current_price:.2f}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 **التقييم وصنع القرار:**\n\n{ai_text}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 الاستخدام المتبقي: {remaining}"
            )
            await context.bot.delete_message(chat_id=user_id, message_id=loading_msg.message_id)
            await context.bot.send_message(chat_id=user_id, text=deep_report, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error analytical process: {e}")
        await context.bot.send_message(chat_id=user_id, text="⚠️ حدث خطأ أثناء التحليل.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ أمر مخصص للمسؤول.")
        return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT tier_level, COUNT(*) FROM users GROUP BY tier_level")
    tiers_summary = cursor.fetchall()
    conn.close()

    summary_text = ""
    for t_lvl, count in tiers_summary:
        tier_label = {0: "مجاني", 1: "أساسي $20", 2: "متقدم $50", 3: "VIP $99"}.get(t_lvl, "غير معروف")
        summary_text += f"• **{tier_label}:** {count} مستخدم\n"

    admin_msg = (
        "💼 **لوحة تحكم إدارة الاشتراكات (Admin)**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📊 إجمالي المستخدمين: {total_users}\n\n"
        f"📋 تفاصيل الباقات:\n{summary_text}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "لتفعيل باقة مشترك:\n`/activate [User_ID] [Tier_Level]`"
    )
    await update.message.reply_text(admin_msg, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 المشتركون المدفوعون", callback_data="adm_list_premium")],
        [InlineKeyboardButton("🔄 تصفير عداد الاستخدام يدوياً", callback_data="adm_reset_usage")]
    ]), parse_mode="Markdown")

async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ مثال: `/activate 12345678 3`")
        return
    try:
        target_id = int(context.args[0])
        tier = int(context.args[1])
        if tier not in [0, 1, 2, 3]:
            await update.message.reply_text("❌ المستوى خاطئ.")
            return
        set_tier_level(target_id, tier)
        await update.message.reply_text(f"✅ تم تفعيل الباقة {tier} للمستخدم: `{target_id}`")
        try:
            await context.bot.send_message(chat_id=target_id, text=f"🎉 **مبروك! تم تفعيل باقتك للمستوى: {tier}**")
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ خطأ في المدخلات.")

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handled = await handle_payment_proof(update, context)
    if not handled:
        await handle_image_analysis(update, context)

async def main():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(reset_daily_usage, 'cron', hour=0, minute=0)
    scheduler.start()

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingServer)
    logging.info(f"🌐 سيرفر الويب يعمل على المنفذ: {port}")
    server.timeout = 0.1

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("activate", activate_user))
    application.add_handler(CommandHandler("alert", create_alert_command))
    application.add_handler(CommandHandler("risk", risk_calculator_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fetch_and_analyze))

    application.job_queue.run_daily(auto_post_to_channel, time=datetime.time(7, 0))
    application.job_queue.run_repeating(check_alerts_job, interval=300)

    await application.initialize()
    await application.start()
    
    updater = application.updater
    await updater.start_polling()

    try:
        while True:
            server.handle_request()
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await updater.stop()
        await application.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
