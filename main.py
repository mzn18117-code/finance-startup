from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from config import TELEGRAM_TOKEN
import yfinance as yf
import threading
from web import run

# تشغيل السيرفر
threading.Thread(target=run).start()

# 🟢 /start (القائمة الرئيسية)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("📊 تحليل سهم", callback_data="analyze")],
        [InlineKeyboardButton("💼 عن البوت", callback_data="about")]
    ]

    msg = "🤖 مرحباً بك في بوت التحليل الذكي\nاختر من القائمة:"

    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))


# 🟡 الأزرار
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "about":
        await q.edit_message_text("📌 هذا بوت تحليل أسهم باستخدام الذكاء الاصطناعي")

    elif q.data == "analyze":
        keyboard = [
            [InlineKeyboardButton("AAPL 🍎", callback_data="AAPL")],
            [InlineKeyboardButton("TSLA 🚗", callback_data="TSLA")],
            [InlineKeyboardButton("BTC ₿", callback_data="BTC-USD")]
        ]
        await q.edit_message_text("اختر السهم:", reply_markup=InlineKeyboardMarkup(keyboard))

    else:
        symbol = q.data
        data = yf.Ticker(symbol).history(period="1d")

        price = data["Close"].iloc[-1]

        await q.edit_message_text(f"📊 {symbol}\n💰 السعر الحالي: {price}")


# تشغيل البوت
app = Application.builder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(buttons))

app.run_polling()
