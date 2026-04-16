from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_IDS, GEMINI_MODEL, SUB_PRICE
from database import get_all_users, get_all_active_users, add_reminder
import logging
import asyncio

logger = logging.getLogger(__name__)


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает статистику бота (только для админов).
    Проверка происходит в bot.py через filters.User.
    """
    logger.info(f"Admin {update.effective_user.id} requested stats")
    
    total_users = get_all_users()
    active_users = get_all_active_users()
    
    # Подсчитываем метрики
    total_count = len(total_users)
    active_count = len(active_users)
    conversion = (active_count / total_count * 100) if total_count > 0 else 0
    
    stats_text = (
        f"📊 <b>Статистика MADONNA</b>\n\n"
        f"👥 Всего пользователей: <b>{total_count}</b>\n"
        f"💎 Premium (активных): <b>{active_count}</b>\n"
        f"📈 Конверсия: <b>{conversion:.1f}%</b>\n\n"
        f"⚙️ Техническое:\n"
        f"• Модель ИИ: {GEMINI_MODEL}\n"
        f"• Цена подписки: {SUB_PRICE}₽\n"
    )
    
    await update.message.reply_text(stats_text, parse_mode='HTML')


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Рассылка сообщения всем пользователям.
    Использование: /broadcast Текст сообщения
    """
    if not context.args:
        await update.message.reply_text("Использование: /broadcast Ваше сообщение")
        return
    
    message_text = " ".join(context.args)
    users = get_all_users()
    
    sent = 0
    failed = 0
    
    status_message = await update.message.reply_text(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user.tg_id,
                text=f"📢 <b>Сообщение от Мадонны:</b>\n\n{message_text}",
                parse_mode='HTML'
            )
            sent += 1
            
            # Задержка чтобы не попасть в лимиты Telegram (30 сообщений в секунду)
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user.tg_id}: {e}")
            failed += 1
    
    # Обновляем статусное сообщение
    await status_message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно: {sent}\n"
        f"Не удалось: {failed}"
    )
    
    logger.info(f"Admin broadcast completed. Sent: {sent}, Failed: {failed}")


async def admin_test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Тестовая отправка напоминания себе.
    Использование: /testreminder water
    """
    if not context.args:
        await update.message.reply_text("Использование: /testreminder [water|food|sleep]")
        return
    
    reminder_type = context.args[0].lower()
    user_id = update.effective_user.id
    
    test_messages = {
        'water': "💧 Тест: Не забудь выпить водичку!",
        'food': "🍽️ Тест: Пора пообедать!",
        'sleep': "🌙 Тест: Пора готовиться ко сну!"
    }
    
    message = test_messages.get(reminder_type, "Тестовое напоминание")
    
    try:
        await context.bot.send_message(chat_id=user_id, text=message)
        await update.message.reply_text(f"✅ Тестовое напоминание '{reminder_type}' отправлено")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
