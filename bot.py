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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = 7763725732
CHANNEL_ID = "@StockHunter_AI"

PRICES = {
    1: 15, 
    2: 49  
}

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("⚠️ تأكد من إدخال TELEGRAM_TOKEN و GEMINI_API_KEY في متغيرات البيئة!")

client = genai.Client(api_key=GEMINI_API_KEY)
DB_FILE = "bot_data.db"

FREE_LIMIT = 3

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
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT
        )
    ''')
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
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET usage_count = 0 WHERE tier_level = 0")
    conn.commit()
    conn.close()

def add_to_favorites(user_id, symbol):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM favorites WHERE user_id = ? AND symbol = ?", (user_id, symbol.upper()))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO favorites (user_id, symbol) VALUES (?, ?)", (user_id, symbol.upper()))
    conn.commit()
    conn.close()

def get_favorites(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT symbol FROM favorites WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

class PingServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("البوت الذكي يعمل بنجاح 🚀".encode("utf-8"))

user_context = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "مستخدم"
    register_or_update_user(user_id, username)
    user_context[user_id] = {}

    main_menu_text = (
        "📊 **مرحباً بك في StockHunter AI** 🚀\n"
        "**منصة التحليل المالي والأسواق الأذكى بالذكاء الاصطناعي.**\n\n"
        "اختر السوق المستهدف أو الخدمة المطلوبة من الخيارات أدناه 👇"
    )
    keyboard = [
        [InlineKeyboardButton("🇺🇸 الأمريكي", callback_data="mkt_us"), InlineKeyboardButton("🇸🇦 السعودي", callback_data="mkt_sa")],
        [InlineKeyboardButton("🇦🇪 الخليجي", callback_data="mkt_gulf"), InlineKeyboardButton("🇪🇬 المصري", callback_data="mkt_egypt")],
        [InlineKeyboardButton("🥇 الذهب", callback_data="mkt_gold"), InlineKeyboardButton("🛢 النفط", callback_data="mkt_oil")],
        [InlineKeyboardButton("🪙 العملات الرقمية", callback_data="mkt_crypto")],
        [InlineKeyboardButton("🔥 أفضل فرصة الآن", callback_data="best_opportunity")],
        [InlineKeyboardButton("⭐ المفضلة", callback_data="pers_fav"), InlineKeyboardButton("💼 محفظتي", callback_data="pers_portfolio")],
        [InlineKeyboardButton("👑 باقات VIP و PRO", callback_data="premium_plans")]
    ]
    
    if update.message:
        await update.message.reply_text(main_menu_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.message.reply_text(main_menu_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id not in user_context:
        user_context[user_id] = {}

    user_data = get_user(user_id)
    tier_level = user_data[1] if user_data else 0

    if data.startswith("mkt_"):
        market = data.replace("mkt_", "").upper()
        user_context[user_id]["market"] = market

        market_names = {"US": "🇺🇸 السوق الأمريكي", "SA": "🇸🇦 السوق السعودي", "GULF": "🇦🇪 السوق الخليجي", "EGYPT": "🇪🇬 السوق المصري", "GOLD": "🥇 الذهب", "OIL": "🛢 النفط", "CRYPTO": "🪙 العملات الرقمية"}
        msg = f"📌 **{market_names.get(market, market)}**\n\nاختر من الخدمات المتاحة للبدء:"
        
        keyboard = [
            [InlineKeyboardButton("🔥 فرص اليوم", callback_data=f"opt_today_{market}"), InlineKeyboardButton("📈 أفضل صاعد", callback_data=f"opt_bull_{market}")],
            [InlineKeyboardButton("📉 أفضل هابط", callback_data=f"opt_bear_{market}"), InlineKeyboardButton("🔍 ابحث عن سهم", callback_data=f"opt_search_{market}")],
            [InlineKeyboardButton("📰 أخبار السوق", callback_data=f"opt_news_{market}")],
            [InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="back_home")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "best_opportunity":
        if tier_level == 0:
            promo_msg = (
                "🚨 **تم اكتشاف فرصة قوية جداً الآن!**\n"
                "• **الأصل:** `NVDA`\n"
                "• **الهدف المتوقع:** `+6.8%`\n"
                "• **وقف الخسارة:** جاهز ومحدد بدقة\n\n"
                "🔒 هذه الإشارة متاحة حصرياً لأعضاء **VIP** و **PRO**.\n"
                "اضغط أدناه للترقية والوصول للصفقة فوراً!"
            )
            keyboard = [[InlineKeyboardButton("👑 اشترك الآن في VIP", callback_data="premium_plans")], [InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="back_home")]]
            await query.edit_message_text(promo_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await query.edit_message_text("⏳ جاري جلب أقوى فرصة استثمارية متطابقة مع معايير الذكاء الاصطناعي...")
            await get_best_opportunity_ai(update, context)

    elif data == "premium_plans":
        plans_msg = (
            "👑 **باقات الاشتراك المميز في StockHunter AI**\n\n"
            "**1️⃣ باقة VIP (الأكثر مبيعاً) - $15 شهرياً**\n"
            "• تحليلات وتقارير غير محدودة\n"
            "• الأهداف السعرية + نقاط الدخول + وقف الخسارة الصارم\n"
            "• ميزة 'أفضل فرصة الآن' للذكاء الاصطناعي\n"
            "• إشارات يومية للأسواق والعملات الرقمية\n\n"
            "**2️⃣ باقة PRO / Elite - $49 شهرياً**\n"
            "• كافة مزايا باقة VIP بالكامل\n"
            "• إدارة المحفظة وحساب المخاطر\n"
            "• تنبيهات مخصصة فورية على الأسعار\n"
            "• صفقات وتحليلات يومية حصرية\n\n"
            "👇 اختر باقتك المفضلة للدفع الآن:"
        )
        keyboard = [
            [InlineKeyboardButton("👑 اشترك في VIP ($15)", callback_data="buy_plan_1")],
            [InlineKeyboardButton("🚀 اشترك في PRO ($49)", callback_data="buy_plan_2")],
            [InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="back_home")]
        ]
        await query.edit_message_text(plans_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("buy_plan_"):
        tier = int(data.split("_")[2])
        price = PRICES.get(tier, 0)
        keyboard = [
            [InlineKeyboardButton("💰 USDT (TRC20/BEP20)", callback_data=f"pay_opt_{tier}_usdt")],
            [InlineKeyboardButton("💳 PayPal", callback_data=f"pay_opt_{tier}_paypal")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="premium_plans")]
        ]
        await query.edit_message_text(f"💳 **اختر وسيلة الدفع المناسبة لك:**\n\nالمبلغ المطلوب: `${price}`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("pay_opt_"):
        parts = data.split("_")
        tier = int(parts[2])
        method = parts[3]
        user_context[user_id]["payment_tier"] = tier
        user_context[user_id]["state"] = "WAITING_PAYMENT_PROOF"

        usdt_addr = "TXxxxxxxxxxxxxxxxxxxxxxxxx"
        pp_link = "https://paypal.me/yourname"

        if method == "usdt":
            msg = f"💰 **الدفع عبر USDT**\n\nالمبلغ: `${PRICES[tier]}`\n\nالعنوان (TRC20):\n`{usdt_addr}`\n\n📸 بعد إتمام التحويل، أرسل صورة الإثبات مباشرة هنا."
        else:
            msg = f"💳 **الدفع عبر PayPal**\n\nالمبلغ: `${PRICES[tier]}`\n\nرابط الدفع:\n{pp_link}\n\n📸 بعد التحويل، أرسل صورة الإثبات هنا."
        
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="premium_plans")]]), parse_mode="Markdown")

    elif data.startswith("opt_"):
        action = data.split("_")[1]
        market = data.split("_")[2]
        
        if action == "search":
            await query.edit_message_text(f"⌨️ **أرسل رمز السهم أو الأصل الذي تبحث عنه الآن (مثال: AAPL أو 2222.SR):**")
            user_context[user_id]["state"] = "AWAITING_SYMBOL_INPUT"
        elif action == "today":
            await query.edit_message_text("⏳ جاري تحليل واستخراج أقوى الفرص الساخنة لليوم...")
            await fetch_market_insights(update, context, market, "HOT")
        elif action == "bull":
            await query.edit_message_text("⏳ جاري جلب أفضل الأسهم الصاعدة حالياً...")
            await fetch_market_insights(update, context, market, "BULL")
        elif action == "bear":
            await query.edit_message_text("⏳ جاري جلب الأسهم الأكثر هبوطاً وتصحيحاً...")
            await fetch_market_insights(update, context, market, "BEAR")
        elif action == "news":
            await query.edit_message_text("⏳ جاري تجميع وتحليل أحدث أخبار السوق...")
            await fetch_market_insights(update, context, market, "NEWS")

    elif data == "pers_fav":
        favs = get_favorites(user_id)
        if not favs:
            await query.edit_message_text("📂 قائمة المفضلة لديك فارغة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="back_home")]]))
        else:
            keyboard = [[InlineKeyboardButton(f"🔍 تحليل {sym}", callback_data=f"sym_direct_{sym}")] for sym in favs]
            keyboard.append([InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="back_home")])
            await query.edit_message_text("⭐ **قائمة أسهمك المفضلة:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "pers_portfolio":
        if tier_level < 2:
            await query.edit_message_text(
                "🚨 **هذه الميزة متاحة للمشتركين PRO فقط!**\n\n"
                "تمكنك باقة PRO من تتبع محفظتك وحساب المخاطر لصفقاتك بدقة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 الترقية لباقة PRO", callback_data="premium_plans")], [InlineKeyboardButton("🔙 العودة", callback_data="back_home")]]),
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("📂 جاري جلب بيانات محفظتك الشخصية...")

    elif data.startswith("sym_direct_"):
        symbol = data.replace("sym_direct_", "")
        await fetch_and_analyze(update, context, direct_symbol=symbol)

    elif data == "back_home":
        await query.message.delete()
        await start(update, context)

async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص للمطور فقط.")
        return

    try:
        target_id = int(context.args[0])
        tier = int(context.args[1])
        set_tier_level(target_id, tier)
        
        tier_names = {0: "مجاني 🆓", 1: "VIP 👑", 2: "PRO / Elite 🚀"}
        await update.message.reply_text(f"✅ تم تفعيل باقة **{tier_names.get(tier, 'غير معروفة')}** للمستخدم `{target_id}` بنجاح!")
        
        await context.bot.send_message(
            chat_id=target_id, 
            text=f"🎉 تهانينا! تم تفعيل اشتراكك في باقة **{tier_names.get(tier)}** بنجاح. استمتع بكافة المزايا الآن!"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ الصيغة خاطئة. استخدم:\n`/activate [ID] [Level]`", parse_mode="Markdown")

async def fetch_and_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE, direct_symbol=None):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    usage_count, tier_level = user_data[0], user_data[1]

    if tier_level == 0 and usage_count >= FREE_LIMIT:
        promo = (
            "🚨 **انتهت تحليلاتك المجانية الـ 3 اليوم.**\n"
            "للحصول على تحليلات غير محدودة + أهداف سعرية ووقف خسارة دقيق:\n\n"
            "🔒 **اشترك الآن في باقة VIP.**"
        )
        await context.bot.send_message(chat_id=user_id, text=promo, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👑 اشترك في VIP", callback_data="premium_plans")]]), parse_mode="Markdown")
        return

    symbol = direct_symbol.upper().strip() if direct_symbol else update.message.text.upper().strip()
    loading = await context.bot.send_message(chat_id=user_id, text=f"⏳ جاري فحص وتحليل `{symbol}`...")

    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="1mo")
        if history.empty:
            history = ticker.history(period="1wk")
            
        if history.empty:
            await context.bot.delete_message(chat_id=user_id, message_id=loading.message_id)
            await context.bot.send_message(chat_id=user_id, text=f"❌ الرمز `{symbol}` غير متاح أو غير موجود حالياً.")
            return

        current_p = float(history['Close'].dropna().iloc[-1])
        change = ((current_p - float(history['Close'].iloc[0])) / float(history['Close'].iloc[0])) * 100

        if tier_level == 0:
            increment_usage(user_id)
            prompt = f"قم بعمل تحليل سريع لسهم {symbol}: السعر الحالي {current_p}, الأداء خلال الفترة {change:.1f}%. اعط ملخص سريع جداً باللغة العربية دون نجوم."
            res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            ai_text = res.text
            
            report = (
                f"📊 **تحليل مجاني لـ:** `{symbol}`\n"
                f"💰 **السعر الحالي:** {current_p:.2f}\n"
                f"📈 **أداء الفترة:** {change:+.2f}%\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 **التقرير المختصر:**\n\n{ai_text}\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                "🔒 الأهداف السعرية العميقة ووقف الخسارة متوفرة للمشتركين VIP."
            )
        else:
            prompt = f"""
            أنت محلل أسواق أول ومستشار مالي. حلل {symbol}: السعر الحالي {current_p}, أداء الفترة {change:.2f}%.
            اكتب تقرير احترافي وعميق للمشتركين باللغة العربية تماماً ودون نجوم:
            1. تقييم الأصل (فرصة شراء أم بيع أم تصحيح).
            2. الأهداف السعرية القريبة والبعيدة.
            3. وقف الخسارة الصارم.
            """
            res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            ai_text = res.text

            report = (
                f"📊 **التقرير الاحترافي للمشتركين لـ:** `{symbol}`\n"
                f"💰 **السعر الحالي:** {current_p:.2f}\n"
                f"📈 **الأداء:** {change:+.2f}%\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 **تحليل وتحركات الذكاء الاصطناعي الكاملة:**\n\n{ai_text}\n"
            )

        add_to_favorites(user_id, symbol)
        keyboard = [[InlineKeyboardButton("🔝 العودة للرئيسية", callback_data="back_home")]]
        await context.bot.delete_message(chat_id=user_id, message_id=loading.message_id)
        await context.bot.send_message(chat_id=user_id, text=report, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Analysis error: {e}")
        await context.bot.delete_message(chat_id=user_id, message_id=loading.message_id)
        await context.bot.send_message(chat_id=user_id, text="⚠️ حدث خطأ أثناء التحليل المالي.")

async def fetch_market_insights(update: Update, context: ContextTypes.DEFAULT_TYPE, market, info_type):
    user_id = update.effective_user.id
    prompt = f"أنت محلل مالي خبير ومحترف. اعط تقريراً متكاملاً حول {info_type} في السوق {market} باللغة العربية تماماً دون نجوم."
    try:
        # تصحيح الموديل ليكون مطابقاً تماماً للمكتبة الرسمية
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        ai_text = res.text
        keyboard = [[InlineKeyboardButton("🔙 العودة للسوق", callback_data=f"mkt_{market.lower()}"), InlineKeyboardButton("🔝 العودة للرئيسية", callback_data="back_home")]]
        await context.bot.send_message(chat_id=user_id, text=ai_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Insight execution error: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_home")]]
        await context.bot.send_message(chat_id=user_id, text="⚠️ تعذر استخراج تقارير السوق حالياً بسبب مشكلة في الاتصال بالذكاء الاصطناعي.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def get_best_opportunity_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prompt = (
        "أنت محلل أول لصناديق الاستثمار. حدد فرصة استثمارية واحدة حالية وممتازة بالسوق العالمي أو الرقمي. "
        "اكتب تقريراً دقيقاً باللغة العربية دون نجوم: الأصل، سعر الدخول، الهدف المتوقع، وقف الخسارة، وتحليل المخاطر."
    )
    try:
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        ai_text = res.text
        keyboard = [[InlineKeyboardButton("🔝 العودة للرئيسية", callback_data="back_home")]]
        await context.bot.send_message(chat_id=user_id, text=f"🔥 **أقوى فرصة استثمارية تم اكتشافها:**\n\n{ai_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Opportunity execution error: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_home")]]
        await context.bot.send_message(chat_id=user_id, text="⚠️ تعذر استخراج الفرصة حالياً.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def post_daily_opportunities(context: ContextTypes.DEFAULT_TYPE = None):
    logging.info("بدء جلب الفرص اليومية لإرسالها للقناة...")
    prompt = (
        "أنت مستشار مالي ومحلل فني خبير. حدد 5 فرص استثمارية ساخنة ومتنوعة لليوم من أسواق متعددة: "
        "(مثل: سهم أمريكي، سهم سعودي، عملة رقمية، الذهب، والنفط). "
        "لكل فرصة، حدد الآتي باللغة العربية بأسلوب احترافي ودون استخدام النجوم:\n"
        "1. اسم الأصل/الأداة المالية\n"
        "2. سبب اختيار الفرصة\n"
        "3. سعر الدخول المتوقع\n"
        "4. الهدف الأول والهدف الثاني\n"
        "5. وقف الخسارة الدقيق\n\n"
        "اكتب عنوان جذاب للمنشور في البداية."
    )
    try:
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        ai_text = res.text

        msg = (
            "🔥 **الفرص اليومية الساخنة من StockHunter AI** 🔥\n"
            f"📅 التاريخ: {datetime.date.today().strftime('%Y-%m-%d')}\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"{ai_text}\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🤖 لتحليلات مخصصة وإشارات فورية، ابدأ استخدام البوت الآن!"
        )

        bot = context.bot if context else Application.builder().token(TELEGRAM_TOKEN).build().bot
        await bot.send_message(chat_id=CHANNEL_ID, text=msg, parse_mode="Markdown")
        logging.info("تم إرسال الفرص الخمس بنجاح إلى القناة!")
    except Exception as e:
        logging.error(f"Daily posting error: {e}", exc_info=True)

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_context and user_context[user_id].get("state") == "AWAITING_SYMBOL_INPUT":
        user_context[user_id]["state"] = None
        await fetch_and_analyze(update, context)
    else:
        await fetch_and_analyze(update, context)

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_context and user_context[user_id].get("state") == "WAITING_PAYMENT_PROOF":
        tier = user_context[user_id].get("payment_tier")
        photo = await update.message.photo[-1].get_file()
        file = await photo.download_as_bytearray()
        
        caption = f"💰 **إثبات دفع جديد**\n\n👤 User ID: `{user_id}`\n📦 الباقة المطلوبة: Level `{tier}`"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تفعيل واشتراك", callback_data=f"approve_sub_{user_id}_{tier}")]])
        
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=file, caption=caption, reply_markup=keyboard, parse_mode="Markdown")
        await update.message.reply_text("✅ تم إرسال الإثبات بنجاح. سيقوم الأدمن بمراجعته وتفعيل باقتك فوراً!")
        user_context[user_id]["state"] = None

def main():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(reset_daily_usage, 'cron', hour=0, minute=0)
    scheduler.add_job(lambda: asyncio.run(post_daily_opportunities()), 'cron', hour=4, minute=0)
    scheduler.start()

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingServer)
    server.timeout = 0.1

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("activate", activate_user))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    async def start_bot():
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())

    try:
        while True:
            server.handle_request()
            loop.run_until_complete(asyncio.sleep(1))
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        loop.run_until_complete(application.updater.stop())
        loop.run_until_complete(application.shutdown())

if __name__ == '__main__':
    main()
