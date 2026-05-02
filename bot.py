import os
import sqlite3
import logging
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- الإعدادات الأساسية ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
HUNTER_API_URL = "https://hunter-api-spzs.onrender.com/analyze/"
HUNTER_API_KEY = "MASTER_HUNTER_2026"
ADMIN_ID = 7763725732  # معرفك كمدير

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- نظام الحماية وقاعدة البيانات ---
def init_db():
    conn = sqlite3.connect("hunter_pro.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, tier TEXT DEFAULT 'FREE', usage INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

# --- خادم الاستضافة (Keep-Alive) ---
class WebServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"StockHunter Pro is Active")

# --- وظائف المساعدة ---
def get_user_status(user_id):
    conn = sqlite3.connect("hunter_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT tier, usage FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return 'FREE', 0
    return row

def update_usage(user_id):
    conn = sqlite3.connect("hunter_pro.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET usage = usage + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- منطق البوت الاحترافي ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier, usage = get_user_status(user_id)
    
    welcome_text = (
        "💎 **StockHunter AI - النسخة الاحترافية**\n\n"
        "مرحباً بك في المحرك الأقوى لرصد الحيتان وتحليل الأسواق:\n"
        "🇺🇸 **الأمريكي** | 🇸🇦 **السعودي** | 🇦🇪 **الإماراتي** | 🪙 **الكريبتو**\n\n"
        "🔹 **حالة الحساب:** " + ("الملكي 👑" if tier != 'FREE' else "المجاني 🆓") + "\n"
        "🔹 **التحليلات اليومية:** " + str(usage) + "/3\n\n"
        "🚀 **أرسل رمز السهم مباشرة (مثال: AAPL أو 2222.SR) للتحليل:**"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔥 أقوى الفرص الآن", callback_data="get_best")],
        [InlineKeyboardButton("👑 ترقية الحساب (VIP)", callback_data="upgrade")],
        [InlineKeyboardButton("📖 دليل الاستخدام", callback_data="guide")]
    ]
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    symbol = update.message.text.upper().strip()
    tier, usage = get_user_status(user_id)

    # التحقق من حدود المجاني
    if tier == 'FREE' and usage >= 3:
        await update.message.reply_text("🚨 **عذراً!** لقد استهلكت جميع محاولاتك المجانية اليوم.\n\nقم بالترقية للباقة الملكية للحصول على تحليلات غير محدودة.",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👑 اشترك الآن", callback_data="upgrade")]]), parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"🔍 **جاري فحص `{symbol}` في الأسواق العالمية...**")

    try:
        # الاتصال بمحرك Hunter API الخاص بك
        headers = {"x-api-key": HUNTER_API_KEY}
        response = requests.get(f"{HUNTER_API_URL}{symbol}", headers=headers, timeout=15)
        
        if response.status_code != 200:
            await msg.edit_text(f"❌ **الرمز `{symbol}` غير صحيح أو غير متوفر.**\nيرجى التأكد من الرمز (مثال: AAPL للأسهم الأمريكية أو 2222.SR للسعودي).")
            return

        data = response.json()
        res = data['analysis']
        strat = data['strategy']
        
        # تنسيق التقرير الاحترافي
        report = (
            f"📈 **تقرير التحليل الرقمي: {symbol}**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💵 **السعر:** {data['metadata']['price']} {data['metadata']['currency']}\n"
            f"🚦 **الإشارة:** `{res['signal']}`\n"
            f"🌊 **رادار الحيتان:** {res['whale_radar']}\n"
            f"🌡 **قوة السهم:** {res['health_score']}\n"
            f"📊 **مؤشر RSI:** {res['rsi_value']}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **خطة الدخول والخروج:**\n"
            f"✅ **سعر الدخول:** {strat['entry']}\n"
            f"🚀 **الهدف الأول:** {strat['target']}\n"
            f"🛡 **وقف الخسارة:** {strat['stop_loss']}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📢 *التحليل يعتمد على خوارزمية Hunter v3.0 الذكية*"
        )

        update_usage(user_id)
        await msg.edit_text(report, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text("⚠️ **عذراً، حدث خطأ فني.** حاول مرة أخرى خلال دقائق.")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "upgrade":
        await query.message.reply_text("💳 **الباقة الملكية (VIP):**\n\n- تحليلات غير محدودة لجميع الأسواق.\n- تنبيهات رادار الحيتان اللحظية.\n- دعم فني مباشر.\n\nتواصل مع المدير للتفعيل: @YourUsername")
    elif query.data == "guide":
        await query.message.reply_text("💡 **كيفية الاستخدام:**\n\n1. للأسهم الأمريكية: أرسل الرمز مباشرة (مثل NVDA).\n2. للأسهم السعودية: أرسل الرمز متبوعاً بـ .SR (مثل 2222.SR).\n3. للعملات الرقمية: أرسل الرمز متبوعاً بـ -USD (مثل BTC-USD).")

# --- تشغيل البوت ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_analysis))
    
    print("🚀 Hunter Bot Pro is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
