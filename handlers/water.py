from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import add_water, get_user, get_today_water
from utils.text_messages import WATER_REMINDERS
import logging

logger = logging.getLogger(__name__)


async def handle_water_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик нажатий кнопок воды.
    Callback data: water_250, water_500, water_1000
    """
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if not user:
        await query.edit_message_text("Сначала зарегистрируйтесь — /start")
        return
    
    # Определяем сколько мл выпил
    try:
        callback_data = query.data  # например "water_250"
        ml = int(callback_data.split('_')[1])
    except (IndexError, ValueError, AttributeError):
        logger.error(f"Invalid water callback: {query.data}")
        await query.edit_message_text("Ошибка. Попробуйте ещё раз.")
        return
    
    # Сохраняем в БД
    add_water(user.tg_id, ml)
    
    # Получаем общее количество за день
    _, total_ml = get_today_water(user.tg_id)
    glasses = total_ml // 250
    
    # Формируем сообщение
    message = (
        f"💧 Отлично! Вы выпили {ml} мл воды.\n\n"
        f"Сегодня уже: {total_ml} мл ({glasses} стаканов из 8)\n"
    )
    
    # Добавляем мотивацию если достигли цели
    if glasses >= 8:
        message += "\n🎉 Поздравляю! Вы выполнили норму воды на сегодня!"
    else:
        # Показываем ближайшее напоминание из списка
        if glasses < len(WATER_REMINDERS):
            next_reminder = WATER_REMINDERS[glasses]
            # Убираем имя из шаблона, так как уже знаем кому пишем
            message += f"\n💡 {next_reminder.replace('Доброе утро, красотка', 'Следующий стакан').replace('Вы', 'Ты')}"
    
    # Кнопки для добавления ещё воды
    keyboard = [
        [InlineKeyboardButton("🥛 Ещё 250 мл", callback_data="water_250")],
        [InlineKeyboardButton("💧 Мой прогресс", callback_data="profile_show")],
        [InlineKeyboardButton("🏠 В меню", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup)
    logger.info(f"User {user.tg_id} added {ml}ml water, total: {total_ml}ml")
