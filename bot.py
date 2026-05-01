إليك الكود المحدّث والكامل للبوت، بعد إضافة الذهب، والسلع، ومؤشرات الأسواق، مع تطبيق نظام الصلاحيات المتدرج والذكي.

---

## 🛠️ كيف تم توزيع الأسواق والصلاحيات في النسخة الجديدة؟

تم ربط الصلاحيات مباشرة بمستوى الاشتراك (`tier_level`) كالتالي:

| فئة الاشتراك | الأسواق المتاحة للاستعراض | مميزات الخدمة والتحليل |
| :--- | :--- | :--- |
| **0 - المجاني** | السوق الأمريكي فقط | التحليل الفني الأساسي فقط (3 محاولات يومياً) |
| **1 - باقة 20$** | السوق الأمريكي + السوق السعودي والخليجي | التحليل المالي والفني الذكي (20 محاولة يومياً) |
| **2 - باقة 50$** | الأمريكي + السعودي والخليجي + **الذهب والنفط والسلع** | استعلامات مفتوحة + محفظة استثمارية واحدة |
| **3 - VIP 99$** | **جميع الأسواق والسلع + المؤشرات العالمية والعملات الرقمية الكبرى** | استعلامات مفتوحة + محافظ متعددة + تحليل VIP عالي الدقة والصرامة |

---

### 📂 الكود البرمجي الكامل للبوت (انسخه بالكامل):

```python
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

# معرف القناة للنشر التلقائي
CHANNEL_ID = "@StockHunter_AI" 

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("⚠️ خطأ: تأكد من إدخال TELEGRAM_TOKEN و GEMINI_API_KEY في متغيرات البيئة!")

client = genai.Client(api_key=GEMINI_API_KEY)
DB_FILE = "bot_data.db"

# الحدود اليومية للباقات
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
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN tier_level INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass 
    conn.commit()
    conn.close()

init_db()

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

# دوال إدارة المحفظة الافتراضية
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
        logging.error(f"Error in RSI calculation: {e}")
        return 50.0

user_context = {}

# 3. سيرفر الويب المتوافق مع Render
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

# 4. وظيفة النشر التلقائي في القناة
async def auto_post_to_channel(context: ContextTypes.DEFAULT_TYPE):
    symbol = "NVDA"
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo")
        if history is None or history.empty:
            return

        current_price = float(history['Close'].dropna().iloc[-1])
        rsi_value = calculate_rsi(history)
        ma_50_series = history['Close'].rolling(window=min(len(history), 50)).mean().dropna()
        ma_50 = float(ma_50_series.iloc[-1]) if not ma_50_series.empty else current_price

        prompt = f"""
        أنت مستشار مالي معتمد. حلل سهم {symbol} وقدم إجابة واضحة لمتابعي القناة:
        - السعر الحالي: {current_price:.2f}
        - مؤشر RSI: {rsi_value:.2f}
        - المتوسط المتحرك 50 يوم: {ma_50:.2f}
        اكتب التقرير باللغة العربية كالتالي (تجنب النجوم والشرطات السفلية تماماً):
        1. القرار النهائي (شراء قوي أو شراء حذر أو مراقبة أو بيع).
        2. الأسباب الفنية والمالية باختصار.
        3. خطة التداول المباشرة (نقطة الدخول، الهدف، وقف الخسارة).
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        ai_text = response.text if response and hasattr(response, 'text') else "تعذر توليد التحليل الذكي حالياً."

        channel_msg = (
            f"📢 **تقرير البوت اليومي المجاني**\n"
            f"🔍 **السهم المختار:** {symbol}\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **السعر الحالي:** {current_price:.2f}\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 **تحليل الذكاء الاصطناعي وصنع القرار:**\n\n{ai_text}\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🤖 لتجربة البوت مجاناً أو الاشتراك:\n"
            "👉 @StockHunter_Pro_bot"
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=channel_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error auto posting to channel: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    register_or_update_user(user_id, username)
    
    welcome_msg = (
        "🤖 **مرحباً بك في StockHunter AI V10.0** 📈\n"
        "**مستشارك المالي الذكي لإدارة وتحليل الأسهم والأسواق والسلع**\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 **آلية عمل البوت:**\n"
        "يقوم البوت بالربط اللحظي مع الأسواق المالية (الأسهم، الذهب، السلع، العملات الرقمية) "
        "ثم يدمج البيانات الحية بمؤشرات فنية ومالية دقيقة لتتم معالجتها بواسطة محرك AI متطور.\n\n"
        "👑 **صلاحيات ومميزات الباقات:**\n"
        "• **🆓 النسخة المجانية:** تتيح لك تحليل السوق الأمريكي فقط (فني) | 3 استعلامات يومياً.\n"
        "• **💎 الباقة الأساسية ($20):** تشمل السوق الأمريكي والخليجي (فني + مالي) | 20 استعلام يومياً.\n"
        "• **🔥 الباقة المتقدمة ($50):** تشمل ما سبق + (الذهب والنفط والسلع) | استعلامات غير محدودة + المحفظة الرقمية.\n"
        "• **👑 باقة VIP المميزة ($99):** تشمل كافة الأسواق والسلع والمؤشرات والعملات الرقمية الكبرى | دعم الـ AI الأعمق والأكثر دقة.\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "👇 **يرجى اختيار وجهتك من الأزرار أدناه للبدء:**"
    )
    keyboard = [
        [InlineKeyboardButton("🏁 البدء واستعراض الأسواق المتاحة لك", callback_data="tier_free")],
        [InlineKeyboardButton("💎 باقات الاشتراك المميز (Premium)", callback_data="tier_premium_info")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    user_data = get_user(user_id)
    tier_level = user_data[1] if user_data else 0

    if data == "tier_free":
        # عرض الأسواق المتاحة فقط بناءً على صلاحية المشترك
        msg = "🎯 **الرجاء اختيار السوق أو السلعة التي ترغب بتحليلها:**"
        keyboard = []
        
        # 1. السوق الأمريكي (متاح للكل)
        keyboard.append([InlineKeyboardButton("🇺🇸 السوق الأمريكي", callback_data="mkt_us")])
        
        # 2. السوق الخليجي والسعودي (متاح من Tier 1 فأعلى)
        if tier_level >= 1:
            keyboard.append([InlineKeyboardButton("🇸🇦 السوق الخليجي والسعودي", callback_data="mkt_gulf")])
        else:
            keyboard.append([InlineKeyboardButton("🔒 السوق الخليجي (باقة 20$)", callback_data="alert_tier1")])

        # 3. الذهب والسلع (متاح من Tier 2 فأعلى)
        if tier_level >= 2:
            keyboard.append([InlineKeyboardButton("📀 الذهب، النفط، والسلع", callback_data="mkt_commodities")])
        else:
            keyboard.append([InlineKeyboardButton("🔒 الذهب والسلع (باقة 50$)", callback_data="alert_tier2")])

        # 4. العملات الرقمية والمؤشرات العالمية (متاح فقط لـ Tier 3 VIP)
        if tier_level >= 3:
            keyboard.append([InlineKeyboardButton("📈 المؤشرات العالمية والعملات الرقمية", callback_data="mkt_global_crypto")])
        else:
            keyboard.append([InlineKeyboardButton("🔒 المؤشرات والعملات الرقمية (VIP 99$)", callback_data="alert_tier3")])

        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("alert_tier"):
        req_tier = data.replace("alert_tier", "")
        tier_names = {"1": "الباقة الأساسية ($20)", "2": "الباقة المتقدمة ($50)", "3": "باقة كبار المستثمرين VIP ($99)"}
        alert_msg = f"🔒 **عذراً! هذه الأسواق حصرية لـ {tier_names.get(req_tier)}.**\n\nبإمكانك الترقية وتفعيل حسابك للاستفادة منها."
        keyboard = [
            [InlineKeyboardButton("💎 استعراض خطط الاشتراك والتفعيل", callback_data="tier_premium_info")],
            [InlineKeyboardButton("🔙 العودة للخلف", callback_data="tier_free")]
        ]
        await query.edit_message_text(alert_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "tier_premium_info":
        premium_msg = (
            "👑 **خطط وباقات الاشتراك المتاحة:**\n\n"
            "1️⃣ **الباقة الأساسية - 20$ شهرياً**\n"
            "• 20 محاولة يومية للتحليل الفني والمالي الذكي للسهم.\n"
            "• يفتح لك: السوق الأمريكي + السوق السعودي والخليجي.\n\n"
            "2️⃣ **الباقة المتقدمة - 50$ شهرياً**\n"
            "• استعلامات غير محدودة طوال اليوم.\n"
            "• ميزة المحفظة الافتراضية لحساب الأرباح والخسائر لحظياً.\n"
            "• يفتح لك: الأمريكي + الخليجي + **الذهب والنفط والسلع**.\n\n"
            "3️⃣ **باقة كبار المستثمرين VIP - 99$ شهرياً**\n"
            "• جميع المميزات السابقة.\n"
            "• تحليلات وقرارات عميقة وحازمة من الـ AI مخصصة للصفقات الكبرى.\n"
            "• يفتح لك: **جميع الأسواق والسلع والمؤشرات والعملات الرقمية الكبرى بلا قيود**.\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 **كود حسابك الشخصي:** `{user_id}`\n\n"
            "📩 **لتفعيل الباقة التي تناسبك:**\n"
            "أرسل (إيصال التحويل + كود حسابك الشخصي) إلى الدعم الفني:\n"
            "⚠️ [اضغط هنا لمراسلة الدعم وتفعيل اشتراكك](https://t.me/ShadowMix_Global)"
        )
        keyboard = [[InlineKeyboardButton("🔙 العودة للبداية", callback_data="back_home")]]
        await query.edit_message_text(premium_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "back_home":
        await start(update, context)

    elif data.startswith("mkt_"):
        market_type = data.replace("mkt_", "").upper()
        user_context[user_id] = {"market": market_type}
        
        msg = "💡 **اختر الخدمة المطلوبة:**"
        keyboard = [
            [InlineKeyboardButton("📊 تحليل فني ومؤشرات السعر", callback_data="srv_tech")],
            [InlineKeyboardButton("🔬 تحليل مالي وفني عميق وصنع القرار (AI)", callback_data="srv_deep")]
        ]
        
        if tier_level >= 2:
            keyboard.append([InlineKeyboardButton("📂 استعراض محفظتي الاستثمارية", callback_data="port_view")])
            keyboard.append([InlineKeyboardButton("➕ إضافة سهم للمحفظة", callback_data="port_add")])
            keyboard.append([InlineKeyboardButton("🗑️ تفريغ المحفظة", callback_data="port_clear")])
            
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("srv_"):
        srv_type = "TECH" if data == "srv_tech" else "DEEP"
        if user_id in user_context:
            user_context[user_id]["service"] = srv_type
        
        market = user_context.get(user_id, {}).get("market")
        
        if market == "US":
            msg = "🇺🇸 **اختر أحد الأسهم الأمريكية الكبرى، أو اكتب الرمز يدوياً:**"
            keyboard = [
                [InlineKeyboardButton("🍏 AAPL", callback_data="sym_AAPL"), InlineKeyboardButton("🚗 TSLA", callback_data="sym_TSLA")],
                [InlineKeyboardButton("💻 MSFT", callback_data="sym_MSFT"), InlineKeyboardButton("🎮 NVDA", callback_data="sym_NVDA")],
                [InlineKeyboardButton("✍️ كتابة رمز سهم آخر يدوياً", callback_data="sym_manual")]
            ]
        elif market == "GULF":
            msg = "🇸🇦 **اختر أحد الأسهم الخليجية/السعودية، أو اكتب الرمز يدوياً:**"
            keyboard = [
                [InlineKeyboardButton("🛢️ أرامكو (2222)", callback_data="sym_2222.SR"), InlineKeyboardButton("🏦 الراجحي (1120)", callback_data="sym_1120.SR")],
                [InlineKeyboardButton("🌿 الإنماء (1150)", callback_data="sym_1150.SR"), InlineKeyboardButton("🏭 سابك (2010)", callback_data="sym_2010.SR")],
                [InlineKeyboardButton("✍️ كتابة رمز سهم آخر يدوياً", callback_data="sym_manual")]
            ]
        elif market == "COMMODITIES":
            msg = "📀 **اختر السلعة المطلوبة، أو اكتب رمزها يدوياً:**"
            keyboard = [
                [InlineKeyboardButton("📀 الذهب (Gold)", callback_data="sym_GC=F"), InlineKeyboardButton("🛢️ النفط الخام", callback_data="sym_CL=F")],
                [InlineKeyboardButton("🥈 الفضة (Silver)", callback_data="sym_SI=F"), InlineKeyboardButton("⛽ الغاز الطبيعي", callback_data="sym_NG=F")],
                [InlineKeyboardButton("✍️ كتابة رمز يدوياً", callback_data="sym_manual")]
            ]
        elif market == "GLOBAL_CRYPTO":
            msg = "📈 **اختر المؤشر أو العملة الرقمية، أو اكتب الرمز يدوياً:**"
            keyboard = [
                [InlineKeyboardButton("🪙 بيتكوين (BTC)", callback_data="sym_BTC-USD"), InlineKeyboardButton("💎 إيثريوم (ETH)", callback_data="sym_ETH-USD")],
                [InlineKeyboardButton("📊 مؤشر S&P 500", callback_data="sym_^GSPC"), InlineKeyboardButton("📉 مؤشر Dow Jones", callback_data="sym_^DJI")],
                [InlineKeyboardButton("✍️ كتابة رمز يدوياً", callback_data="sym_manual")]
            ]
        
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("sym_"):
        symbol = data.replace("sym_", "")
        if symbol == "manual":
            msg = "⌨️ **يرجى إرسال الرمز الآن يدوياً (مثل: NVDA أو 2222.SR أو GC=F):**"
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text(f"⏳ تم اختيار `{symbol}`. جاري جلب البيانات والتحليل الآن...")
            await fetch_and_analyze(update, context, direct_symbol=symbol)

    elif data == "port_view":
        await view_portfolio_action(update, context)
        
    elif data == "port_add":
        user_context[user_id]["state"] = "AWAITING_PORTFOLIO_DATA"
        await query.edit_message_text(
            "➕ **لإضافة أصل مالي إلى محفظتك:**\n\n"
            "يرجى إرسال البيانات بالصيغة التالية تماماً:\n"
            "`رمز الأصل, الكمية, سعر الشراء`\n\n"
            "**مثال:** `AAPL, 10, 175.5` أو `GC=F, 2, 2150.0`", 
            parse_mode="Markdown"
        )
        
    elif data == "port_clear":
        clear_portfolio(user_id)
        await query.edit_message_text("🗑️ تم تفريغ محفظتك الاستثمارية بالكامل بنجاح.", parse_mode="Markdown")

    # أزرار لوحة تحكم المسؤول
    elif data == "adm_list_premium" and user_id == ADMIN_ID:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, tier_level FROM users WHERE tier_level > 0")
        premium_users = cursor.fetchall()
        conn.close()

        if not premium_users:
            await query.message.reply_text("ℹ️ لا يوجد مشتركين مدفوعين حالياً.")
            return

        list_msg = "💎 **قائمة المشتركين المدفوعين حالياً:**\n━━━━━━━━━━━━━━━━━━━\n"
        for u_id, username, tier in premium_users:
            tier_name = {1: "باقة 20$", 2: "باقة 50$", 3: "باقة 99$"}.get(tier)
            list_msg += f"👤 `@{username}` | ID: `{u_id}`\n👑 الباقة: **{tier_name}**\n\n"
            
        await query.message.reply_text(list_msg, parse_mode="Markdown")

    elif data == "adm_reset_usage" and user_id == ADMIN_ID:
        reset_daily_usage()
        await query.message.reply_text("✅ تم تصفير عداد الاستخدام اليومي لجميع المستخدمين بنجاح.")

async def view_portfolio_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stocks = get_portfolio(user_id)
    
    if not stocks:
        msg = "📂 **محفظتك فارغة حالياً.**\nيمكنك البدء بإضافة الأسهم والأصول إليها."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
        return

    loading_msg = await context.bot.send_message(chat_id=user_id, text="🔄 جاري جلب الأسعار اللحظية وحساب المحفظة...")
    
    report = "📂 **تقرير محفظتك الاستثمارية الحالي:**\n"
    report += "━━━━━━━━━━━━━━━━━━━\n"
    
    total_cost = 0.0
    total_value = 0.0
    
    for symbol, qty, buy_p in stocks:
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="1d")
            if history is not None and not history.empty:
                current_p = float(history['Close'].dropna().iloc[-1])
            else:
                current_p = buy_p
        except:
            current_p = buy_p
            
        cost = qty * buy_p
        val = qty * current_p
        profit_loss = val - cost
        p_l_pct = (profit_loss / cost) * 100 if cost > 0 else 0
        
        total_cost += cost
        total_value += val
        
        status_emoji = "🟢" if profit_loss >= 0 else "🔴"
        report += (
            f"📌 **الأصل:** `{symbol}`\n"
            f"   • الكمية: {qty} | سعر الشراء: {buy_p:.2f}\n"
            f"   • السعر الحالي: {current_p:.2f}\n"
            f"   • {status_emoji} الربح/الخسارة: {profit_loss:+.2f} ({p_l_pct:+.2f}%)\n"
            "━━━━━━━━━━━━━━━━━━━\n"
        )
        
    total_p_l = total_value - total_cost
    total_p_l_pct = (total_p_l / total_cost) * 100 if total_cost > 0 else 0
    t_emoji = "🟢" if total_p_l >= 0 else "🔴"
    
    report += (
        f"💰 **إجمالي التكلفة:** {total_cost:.2f}\n"
        f"📈 **القيمة الحالية:** {total_value:.2f}\n"
        f"📊 **صافي الأداء:** {t_emoji} {total_p_l:+.2f} ({total_p_l_pct:+.2f}%)\n"
    )
    
    await context.bot.delete_message(chat_id=user_id, message_id=loading_msg.message_id)
    await context.bot.send_message(chat_id=user_id, text=report, parse_mode="Markdown")

async def fetch_and_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_symbol=None):
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    
    register_or_update_user(user_id, username)
    user_data = get_user(user_id)
    usage_count, tier_level = user_data[0], user_data[1]

    if tier_level == 0 and usage_count >= FREE_LIMIT:
        paywall_msg = "🔒 **انتهت محاولاتك المجانية اليوم (3 محاولات).**"
        keyboard = [[InlineKeyboardButton("💎 تفعيل الباقة المدفوعة", callback_data="tier_premium_info")]]
        await context.bot.send_message(chat_id=user_id, text=paywall_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    elif tier_level == 1 and usage_count >= TIER1_LIMIT:
        paywall_msg = f"🔒 **انتهت محاولاتك لليوم في الباقة الأساسية ({TIER1_LIMIT} محاولة).**"
        keyboard = [[InlineKeyboardButton("💎 الترقية للباقة المتقدمة", callback_data="tier_premium_info")]]
        await context.bot.send_message(chat_id=user_id, text=paywall_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if user_id in user_context and user_context[user_id].get("state") == "AWAITING_PORTFOLIO_DATA" and not direct_symbol:
        try:
            parts = update.message.text.split(",")
            symbol = parts[0].strip().upper()
            qty = float(parts[1].strip())
            buy_price = float(parts[2].strip())
            
            add_to_portfolio(user_id, symbol, qty, buy_price)
            user_context[user_id]["state"] = None
            await update.message.reply_text(f"✅ تم بنجاح إضافة {qty} من `{symbol}` بسعر {buy_price} إلى محفظتك.", parse_mode="Markdown")
            return
        except Exception:
            await update.message.reply_text("⚠️ خطأ في الصيغة. يرجى كتابتها كالمثال: `AAPL, 10, 175.5`")
            return

    if user_id not in user_context or "market" not in user_context[user_id] or "service" not in user_context[user_id]:
        await context.bot.send_message(chat_id=user_id, text="الرجاء البدء بالضغط على /start أولاً لتحديد السوق والخدمة.")
        return

    if direct_symbol:
        symbol = direct_symbol.upper().strip()
    else:
        symbol = update.message.text.upper().strip()

    loading_msg = await context.bot.send_message(chat_id=user_id, text=f"⏳ جاري جلب البيانات وإجراء التحليل الاحترافي لـ {symbol}...")
    
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo")
        
        if history is None or history.empty:
            await context.bot.send_message(chat_id=user_id, text=f"❌ لم يتم العثور على بيانات لـ `{symbol}`.")
            return

        current_price = float(history['Close'].dropna().iloc[-1])
        rsi_value = calculate_rsi(history)
        
        ma_50_series = history['Close'].rolling(window=min(len(history), 50)).mean().dropna()
        ma_50 = float(ma_50_series.iloc[-1]) if not ma_50_series.empty else current_price

        user_srv = user_context[user_id]["service"]
        
        if tier_level < 2:
            increment_usage(user_id)
            remaining = (FREE_LIMIT if tier_level == 0 else TIER1_LIMIT) - (usage_count + 1)
        else:
            remaining = "مفتوح (VIP 👑)"

        if user_srv == "TECH":
            tech_status = "تشبع بيعي (فرصة شراء)" if rsi_value < 35 else "تشبع شرائي (جني أرباح)" if rsi_value > 65 else "حالة مستقرة (حياد)"
            trend = "اتجاه صاعد (Bullish)" if current_price > ma_50 else "اتجاه هابط (Bearish)"
            
            tech_report = (
                f"📊 **التقرير الفني لـ:** {symbol}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **السعر الحالي:** {current_price:.2f}\n"
                f"📉 **مؤشر الـ RSI:** {rsi_value:.2f} ({tech_status})\n"
                f"📈 **الاتجاه العام:** {trend}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 **الاستخدام المتبقي لك اليوم:** {remaining}"
            )
            await context.bot.delete_message(chat_id=user_id, message_id=loading_msg.message_id)
            await context.bot.send_message(chat_id=user_id, text=tech_report, parse_mode="Markdown")

        elif user_srv == "DEEP":
            if tier_level == 0:
                await context.bot.send_message(chat_id=user_id, text="⚠️ هذه الميزة متاحة فقط للمشتركين Premium.")
                return
                
            pe_ratio = "غير متوفر"
            eps = "غير متوفر"
            div_yield = 0.0

            try:
                info = ticker.info
                if isinstance(info, dict):
                    pe_ratio = info.get('trailingPE', 'غير متوفر')
                    eps = info.get('trailingEps', 'غير متوفر')
                    raw_yield = info.get('dividendYield', 0)
                    if raw_yield and 0 < raw_yield < 0.5:
                        div_yield = raw_yield * 100
            except Exception:
                pass

            if tier_level == 3:
                prompt = f"""
                أنت خبير مالي ومحلل مخاطر أول للصفقات الكبرى (VIP). حلل الأصل {symbol} بناءً على الآتي:
                - السعر الحالي: {current_price:.2f}
                - مكرر الربحية: {pe_ratio} | ربحية السهم: {eps}
                - عائد التوزيعات: {div_yield:.2f}%
                - مؤشر RSI: {rsi_value:.2f} | المتوسط المتحرك 50 يوم: {ma_50:.2f}
                
                اكتب التقرير باللغة العربية كالتالي (تجنب النجوم والشرطات السفلية تماماً):
                1. القرار الحاسم لـ VIP (شراء قوي جداً أو شراء حذر أو مراقبة أو بيع فوري).
                2. الأسباب المالية والفنية المتقدمة بدقة.
                3. أهداف التداول المتقدمة (الدخول، الهدف الأول، الهدف الثاني، وقف الخسارة الصارم).
                """
            else:
                prompt = f"""
                أنت مستشار مالي معتمد. حلل {symbol} وقدم إجابة واضحة وموثوقة:
                - السعر الحالي: {current_price:.2f}
                - مكرر الربحية: {pe_ratio} | ربحية السهم: {eps}
                - عائد التوزيعات: {div_yield:.2f}%
                - مؤشر RSI: {rsi_value:.2f} | المتوسط المتحرك 50 يوم: {ma_50:.2f}
                
                اكتب التقرير باللغة العربية كالتالي (تجنب النجوم والشرطات السفلية تماماً):
                1. القرار النهائي (شراء أو مراقبة أو بيع).
                2. الأسباب المالية والفنية باختصار.
                3. خطة التداول المباشرة (نقطة الدخول، الهدف، وقف الخسارة).
                """
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            ai_text = response.text if response and hasattr(response, 'text') else "عذراً، تعذر توليد القرار الذكي حالياً."
            
            tier_name = "VIP 👑" if tier_level == 3 else "Premium 💎"
            deep_report = (
                f"📊 **تقرير المشتركين {tier_name} لـ:** {symbol}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **السعر الحالي:** {current_price:.2f}\n"
                f"📉 **مكرر الربحية (P/E):** {pe_ratio}\n"
                f"📊 **ربحية السهم (EPS):** {eps}\n"
                f"📉 **مؤشر الـ RSI:** {rsi_value:.2f}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 **تقييم البوت وصناعة القرار الاستثماري:**\n\n{ai_text}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 **الاستخدام المتبقي لك اليوم:** {remaining}"
            )
            await context.bot.delete_message(chat_id=user_id, message_id=loading_msg.message_id)
            await context.bot.send_message(chat_id=user_id, text=deep_report, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Error executing analysis for {symbol}: {e}")
        await context.bot.send_message(chat_id=user_id, text=f"⚠️ حدث خطأ أثناء التحليل لـ {symbol}.")

# 5. أوامر لوحة التحكم الخاصة بالمسؤول
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ عذراً، هذا الأمر مخصص لمالك البوت فقط.")
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
        "💼 **لوحة تحكم إدارة الاشتراكات (Admin Dashboard)**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **إجمالي المستخدمين المسجلين:** {total_users} مستخدم\n\n"
        f"📋 **تفاصيل الاشتراكات الحالية:**\n{summary_text}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ **خيارات التحكم السريع:**\n"
        "لتفعيل أو تغيير باقة مشترك، استخدم الأمر:\n"
        "`/activate [User_ID] [Tier_Level]`\n\n"
        "📌 **دليل المستويات:**\n"
        "• `0` = مجاني | `1` = باقة 20$ | `2` = باقة 50$ | `3` = VIP 99$"
    )
    
    keyboard = [
        [InlineKeyboardButton("📋 عرض قائمة المشتركين المدفوعين", callback_data="adm_list_premium")],
        [InlineKeyboardButton("🔄 تصفير عداد الاستخدام يدوياً", callback_data="adm_reset_usage")]
    ]
    await update.message.reply_text(admin_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ مثال: `/activate 12345678 2` لتفعيل باقة 50$")
        return
    try:
        target_id = int(context.args[0])
        tier = int(context.args[1])
        if tier not in [0, 1, 2, 3]:
            await update.message.reply_text("❌ المستوى غير صحيح. اختر بين 0 و 3.")
            return

        set_tier_level(target_id, tier)
        tier_label = {0: "مجانية", 1: "أساسية $20", 2: "متقدمة $50", 3: "VIP $99"}.get(tier)
        
        await update.message.reply_text(f"✅ تم بنجاح تفعيل الباقة **{tier_label}** للمستخدم: `{target_id}`")
        try:
            await context.bot.send_message(chat_id=target_id, text=f"🎉 **مبروك! تم تفعيل اشتراكك في باقة: {tier_label} بنجاح.**\nاضغط على /start لاستعراض ميزاتك الجديدة.")
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ خطأ: يرجى إدخال قيم صحيحة.")

# دالة تشغيل سيرفر الويب وسحب التحديثات في آن واحد
async def main():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(reset_daily_usage, 'cron', hour=0, minute=0)
    scheduler.start()

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingServer)
    logging.info(f"🌐 تم تشغيل سيرفر الويب المدمج على المنفذ: {port}")
    
    server.timeout = 0.1
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("activate", activate_user))
    application.add_handler(CallbackQueryHandler(button_handler))
    # التقاط الأزرار المخصصة للمسؤول
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^adm_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fetch_and_analyze))

    application.job_queue.run_daily(auto_post_to_channel, time=datetime.time(7, 0))

    await application.initialize()
    await application.start()
    
    updater = application.updater
    await updater.start_polling()

    logging.info("🚀 البوت يعمل الآن بكفاءة كاملة على ريندر...")

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
```
