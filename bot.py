import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from brain_v4 import LuciferQuantBrain
from risk_v4 import InstitutionalRisk
import db_manager as db

# إعدادات البوت
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# تهيئة المحركات
brain = LuciferQuantBrain()
risk = InstitutionalRisk()

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    # تسجيل المستخدم إذا كان جديداً
    db.register_user(user_id)
    
    welcome_text = (
        "🛡️ **مرحباً بك في LUCIFER-VOID**\n"
        "محرك الاستخبارات المالية للأسواق الأمريكية والخليجية.\n\n"
        "🔹 /signal [الرمز] - تحليل فوري ومعزز بالذكاء الاصطناعي\n"
        "🔹 /elite - الحصول على إشارات ما قبل السوق (High Confidence)\n"
        "🔹 /referral - رابط الإحالة الخاص بك (اربح توكنات مجانية)\n"
        "🔹 /stats - عرض سجل أداء النظام (Win Rate / Sharpe)"
    )
    await message.reply(welcome_text, parse_mode="Markdown")

@dp.message_handler(commands=['signal'])
async def cmd_signal(message: types.Message):
    user_id = message.from_user.id
    try:
        symbol = message.text.split()[1].upper()
        # فحص الرصيد
        if not db.has_tokens(user_id):
            return await message.reply("⚠️ رصيدك انتهى. اشترك في Pro أو Elite للمتابعة.")

        # محاكاة جلب البيانات وتشغيل المحرك
        tech, sent, vol = 85, 0.6, 70 # بيانات تجريبية
        score = brain.calculate_score(tech, sent, vol)
        plan = risk.get_execution_plan(entry=210.50, vol_index=0.1)

        msg = (
            f"📊 **تحليل السهم: {symbol}**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📈 الثقة: {score}%\n"
            f"💰 الدخول: {plan['entry']}$\n"
            f"🛑 الوقف (SL): {plan['stop_loss']}$\n"
            f"🎯 الهدف الجزئي: {plan['tp_partial']}$\n\n"
            f"💡 *تم خصم 1 توكن من رصيدك.*"
        )
        db.deduct_token(user_id)
        await message.reply(msg, parse_mode="Markdown")
    except IndexError:
        await message.reply("❌ يرجى إدخال رمز السهم، مثال: `/signal AAPL`", parse_mode="Markdown")

@dp.message_handler(commands=['referral'])
async def cmd_referral(message: types.Message):
    user_id = message.from_user.id
    link = f"https://t.me/LuciferVoidBot?start={user_id}"
    await message.reply(f"🤝 **شارك الرابط واربح!**\nعن كل شخص يشترك عبرك، ستحصل على 5 توكنات مجانية.\n\nرابطك: `{link}`", parse_mode="Markdown")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
