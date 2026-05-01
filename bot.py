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
FREE_LIMIT = 3

# 2. تهيئة قاعدة البيانات SQLite
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            usage_count INTEGER DEFAULT 0,
            is_premium INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT usage_count, is_premium FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def register_or_update_user(user_id, username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO users (user_id, username, usage_count, is_premium) VALUES (?, ?, 0, 0)", (user_id, username))
    conn.commit()
    conn.close()

def increment_usage(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def set_premium_status(user_id, status=1):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_premium = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

def reset_daily_usage():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET usage_count = 0 WHERE is_premium = 0")
        conn.commit()
        conn.close()
        logging.info("🔄 تم تصفير عداد الاستخدام اليومي بنجاح.")
    except Exception as e:
        logging.error(f"Error resetting daily usage: {e}")

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
    logging.info(f"📢 جاري جلب التحليل التلقائي لسهم {symbol} لنشره بالقناة...")
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
        أنت مستشار مالي معتمد. حلل سهم {symbol} وقدم إجابة واضحة وموثوقة لمتابعي القناة:
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
        logging.info("✅ تم إرسال المنشور التلقائي للقناة بنجاح.")
    except Exception as e:
        logging.error(f"Error auto posting to channel: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    register_or_update_user(user_id, username)
    
    welcome_msg = (
        "🤖 **أهلاً بك في بوت المستشار المالي V8.6** 📈\n"
        "شريكك لاتخاذ قرارات استثمارية مدروسة ومبنية على بيانات حقيقية.\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "✨ **النسخة المجانية:** تمنحك استعلامات محدودة للأسعار والمؤشرات الفنية.\n"
        "👑 **الاشتراك المدفوع:** تقارير عميقة وصناعة القرار الاستثماري بدون قيود.\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 **الرجاء تحديد خيارك للبدء:**"
    )
    keyboard = [
        [InlineKeyboardButton("🆓 استخدام النسخة المجانية", callback_data="tier_free")],
        [InlineKeyboardButton("💎 تفاصيل الاشتراك المدفوع", callback_data="tier_premium")]
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

    if data == "tier_free":
        msg = "🎯 **لقد اخترت النسخة المجانية**\nالرجاء اختيار السوق الذي ترغب بالعمل عليه:"
        keyboard = [
            [InlineKeyboardButton("🇺🇸 السوق الأمريكي", callback_data="mkt_us")],
            [InlineKeyboardButton("🇸🇦 السوق الخليجي", callback_data="mkt_gulf")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "tier_premium":
        premium_msg = (
            "👑 **ميزات الاشتراك والتحليل العميق (Premium):**\n\n"
            "• حسم القرار الاستثماري بدقة عالية [شراء قوي / مراقبة / بيع] مع الأسباب الفنية والمالية.\n"
            "• تحديد دقيق لنقاط الدخول، الأهداف، ووقف الخسارة.\n"
            "• استعلامات مفتوحة بلا قيود على مدار الساعة.\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💳 **أسعار الاشتراك:**\n"
            "• اشتراك شهري: 20$ فقط\n\n"
            "💰 **طرق الدفع المتاحة:**\n"
            "• تحويل بنكي / PayPal / USDT\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 **كود حسابك الشخصي:** `{user_id}`\n\n"
            "📩 **طريقة التفعيل:**\n"
            "1. قم بتحويل مبلغ الاشتراك عبر الوسيلة المفضلة لديك.\n"
            "2. اضغط على رابط الدعم أدناه وأرسل (إيصال التحويل + كود حسابك الشخصي).\n\n"
            "⚠️ [اضغط هنا لمراسلة الدعم وتفعيل اشتراكك](https://t.me/ShadowMix_Global)"
        )
        keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_home")]]
        await query.edit_message_text(premium_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "back_home":
        await start(update, context)

    elif data.startswith("mkt_"):
        market_type = "US" if data == "mkt_us" else "GULF"
        user_context[user_id] = {"market": market_type}
        msg = "💡 **اختر نوع التحليل المطلوب للسهم:**"
        keyboard = [
            [InlineKeyboardButton("📊 تحليل فني ومؤشرات السعر", callback_data="srv_tech")],
            [InlineKeyboardButton("🔬 تحليل مالي وفني عميق وصنع القرار (AI)", callback_data="srv_deep")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("srv_"):
        srv_type = "TECH" if data == "srv_tech" else "DEEP"
        if user_id in user_context:
            user_context[user_id]["service"] = srv_type
        
        market = user_context.get(user_id, {}).get("market")
        
        if market == "US":
            msg = "🎯 **اختر أحد أشهر الأسهم الأمريكية، أو اختر الكتابة اليدوية:**"
            keyboard = [
                [InlineKeyboardButton("🍏 AAPL", callback_data="sym_AAPL"), InlineKeyboardButton("🚗 TSLA", callback_data="sym_TSLA")],
                [InlineKeyboardButton("💻 MSFT", callback_data="sym_MSFT"), InlineKeyboardButton("🎮 NVDA", callback_data="sym_NVDA")],
                [InlineKeyboardButton("✍️ كتابة رمز سهم آخر يدوياً", callback_data="sym_manual")]
            ]
        else:
            msg = "🎯 **اختر أحد أشهر الأسهم الخليجية/السعودية، أو اختر الكتابة اليدوية:**"
            keyboard = [
                [InlineKeyboardButton("🛢️ أرامكو (2222)", callback_data="sym_2222.SR"), InlineKeyboardButton("🏦 الراجحي (1120)", callback_data="sym_1120.SR")],
                [InlineKeyboardButton("🌿 الإنماء (1150)", callback_data="sym_1150.SR"), InlineKeyboardButton("🏭 سابك (2010)", callback_data="sym_2010.SR")],
                [InlineKeyboardButton("✍️ كتابة رمز سهم آخر يدوياً", callback_data="sym_manual")]
            ]
        
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("sym_"):
        symbol = data.replace("sym_", "")
        if symbol == "manual":
            msg = "⌨️ **يرجى إرسال رمز السهم الآن يدوياً (مثال: NVDA أو 2222.SR):**"
            await query.edit_message_text(msg, parse_mode="Markdown")
        else:
            await query.edit_message_text(f"⏳ تم تحديد السهم `{symbol}`. جاري جلب البيانات والتحليل...")
            class DummyMessage:
                def __init__(self, text):
                    self.text = text
            update.message = DummyMessage(symbol)
            await fetch_and_analyze(update, context)

async def fetch_and_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    
    register_or_update_user(user_id, username)
    user_data = get_user(user_id)
    usage_count, is_premium = user_data[0], user_data[1]

    if is_premium == 0 and usage_count >= FREE_LIMIT:
        paywall_msg = "🔒 **انتهت محاولاتك المجانية لليوم!** يتم تجديد المحاولات تلقائياً كل 24 ساعة."
        keyboard = [[InlineKeyboardButton("💎 تفعيل الاشتراك المدفوع", callback_data="tier_premium")]]
        
        if update.message and hasattr(update.message, 'reply_text'):
            await update.message.reply_text(paywall_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=user_id, text=paywall_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if user_id not in user_context or "market" not in user_context[user_id] or "service" not in user_context[user_id]:
        msg = "الرجاء البدء بالضغط على /start أولاً لتحديد السوق والخدمة."
        if update.message and hasattr(update.message, 'reply_text'):
            await update.message.reply_text(msg)
        else:
            await context.bot.send_message(chat_id=user_id, text=msg)
        return

    symbol = update.message.text.upper().strip() if hasattr(update.message, 'text') else update.message.text
    
    if update.message and hasattr(update.message, 'reply_text'):
        await update.message.reply_text(f"⏳ جاري جلب البيانات وإجراء التحليل الاحترافي لسهم {symbol}...")
    else:
        await context.bot.send_message(chat_id=user_id, text=f"⏳ جاري جلب البيانات وإجراء التحليل الاحترافي لسهم {symbol}...")
    
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3mo")
        
        if history is None or history.empty:
            err_msg = f"❌ لم يتم العثور على بيانات للسهم `{symbol}`."
            if update.message and hasattr(update.message, 'reply_text'):
                await update.message.reply_text(err_msg)
            else:
                await context.bot.send_message(chat_id=user_id, text=err_msg)
            return

        current_price = float(history['Close'].dropna().iloc[-1])
        rsi_value = calculate_rsi(history)
        
        ma_50_series = history['Close'].rolling(window=min(len(history), 50)).mean().dropna()
        ma_50 = float(ma_50_series.iloc[-1]) if not ma_50_series.empty else current_price

        user_srv = user_context[user_id]["service"]
        
        if is_premium == 0:
            increment_usage(user_id)
            remaining = FREE_LIMIT - (usage_count + 1)
        else:
            remaining = "مفتوح (حساب مدفوع 👑)"

        if user_srv == "TECH":
            tech_status = "تشبع بيعي (فرصة شراء)" if rsi_value < 35 else "تشبع شرائي (جني أرباح)" if rsi_value > 65 else "حالة مستقرة (حياد)"
            trend = "اتجاه صاعد (Bullish)" if current_price > ma_50 else "اتجاه هابط (Bearish)"
            
            tech_report = (
                f"📊 التقرير الفني لسهم: {symbol}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"💰 السعر الحالي: {current_price:.2f}\n"
                f"📉 مؤشر الـ RSI: {rsi_value:.2f} ({tech_status})\n"
                f"📈 الاتجاه العام: {trend}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 الاستخدام المتبقي لك اليوم: {remaining}"
            )
            if update.message and hasattr(update.message, 'reply_text'):
                await update.message.reply_text(tech_report)
            else:
                await context.bot.send_message(chat_id=user_id, text=tech_report)

        elif user_srv == "DEEP":
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
            except Exception as info_err:
                logging.warning(f"Info fail for {symbol}: {info_err}")

            prompt = f"""
            أنت مستشار مالي معتمد وصانع قرار استثماري حازم. حلل سهم {symbol} وقدم إجابة واضحة وموثوقة:
            
            بيانات السهم:
            - السعر الحالي: {current_price:.2f}
            - مكرر الربحية: {pe_ratio}
            - ربحية السهم: {eps}
            - عائد التوزيعات: {div_yield:.2f}%
            - مؤشر RSI: {rsi_value:.2f}
            - المتوسط المتحرك 50 يوم: {ma_50:.2f}
            
            اكتب التقرير باللغة العربية كالتالي (تجنب النجوم والشرطات السفلية تماماً):
            
            1. القرار النهائي (شراء قوي أو شراء حذر أو مراقبة أو بيع).
            2. الأسباب المالية والفنية (في 3 نقاط محددة ومقنعة).
            3. خطة التداول المباشرة (نقطة الدخول، الهدف الأول، الهدف الثاني، وقف الخسارة).
            """
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            ai_text = response.text if response and hasattr(response, 'text') else "عذراً، تعذر توليد القرار الذكي حالياً."
            
            deep_report = (
                f"🔬 التحليل والقرار النهائي لسهم: {symbol}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"💰 السعر الحالي: {current_price:.2f}\n"
                f"📉 مكرر الربحية (P/E): {pe_ratio}\n"
                f"📊 ربحية السهم (EPS): {eps}\n"
                f"📉 مؤشر الـ RSI: {rsi_value:.2f}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 تقييم البوت وصناعة القرار:\n\n{ai_text}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 الاستخدام المتبقي لك اليوم: {remaining}"
            )
            if update.message and hasattr(update.message, 'reply_text'):
                await update.message.reply_text(deep_report)
            else:
                await context.bot.send_message(chat_id=user_id, text=deep_report)

    except Exception as e:
        logging.error(f"Error executing analysis for {symbol}: {e}")
        err_msg = f"⚠️ حدث خطأ أثناء التحليل التقني لسهم {symbol}."
        if update.message and hasattr(update.message, 'reply_text'):
            await update.message.reply_text(err_msg)
        else:
            await context.bot.send_message(chat_id=user_id, text=err_msg)

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
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    premium_users = cursor.fetchone()[0]
    conn.close()

    admin_msg = (
        "💼 **لوحة تحكم المسؤول (Admin Panel)**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **إجمالي المستخدمين في البوت:** {total_users}\n"
        f"👑 **عدد المشتركين المدفوعين:** {premium_users}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 **لتفعيل مستخدم جديد ارسل:**\n"
        "`/activate user_id`\n"
        "💡 **لإلغاء تفعيل مستخدم ارسل:**\n"
        "`/deactivate user_id`"
    )
    await update.message.reply_text(admin_msg, parse_mode="Markdown")

async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ مثال: `/activate 12345678`")
        return
    try:
        target_id = int(context.args[0])
        set_premium_status(target_id, 1)
        await update.message.reply_text(f"✅ تم تفعيل باقة Premium بنجاح للمستخدم: `{target_id}`")
        try:
            await context.bot.send_message(chat_id=target_id, text="🎉 **مبروك! تم تفعيل اشتراكك المدفوع بنجاح.**")
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ خطأ: يرجى إدخال ID صحيح.")

async def deactivate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ مثال: `/deactivate 12345678`")
        return
    try:
        target_id = int(context.args[0])
        set_premium_status(target_id, 0)
        await update.message.reply_text(f"❌ تم إلغاء تفعيل باقة Premium للمستخدم: `{target_id}`")
    except ValueError:
        await update.message.reply_text("❌ خطأ: يرجى إدخال ID صحيح.")

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
    application.add_handler(CommandHandler("deactivate", deactivate_user))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fetch_and_analyze))

    # جدولة النشر التلقائي في القناة يومياً الساعة 7:00 صباحاً بالتوقيت العالمي
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
