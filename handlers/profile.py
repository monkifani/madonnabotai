from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_user, get_today_water, get_today_food
from utils.helpers import calculate_calorie_norm, get_water_glasses
from utils.text_messages import MAIN_MENU
import logging

logger = logging.getLogger(__name__)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает профиль пользователя.
    Может вызываться как командой /profile, так и callback'ом.
    """
    # Определяем источник вызова (команда или кнопка)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        send_message = query.edit_message_text
        user_id = update.effective_user.id
    else:
        send_message = update.message.reply_text
        user_id = update.effective_user.id
    
    user = get_user(user_id)
    if not user:
        await send_message("Сначала зарегистрируйтесь — /start")
        return
    
    # Собираем статистику
    _, total_water = get_today_water(user.tg_id)
    _, total_calories = get_today_food(user.tg_id)
    glasses = get_water_glasses(user.tg_id)
    calorie_norm = calculate_calorie_norm(user.weight, user.height, user.age)
    
    # Формируем текст профиля
    profile_text = (
        f"👤 <b>Мой профиль</b>\n\n"
        f"Имя: {user.name}\n"
        f"Возраст: {user.age} лет\n"
        f"Рост: {user.height} см\n"
        f"Вес: {user.weight} кг\n"
        f"Биологический возраст: {user.bio_age or user.age} лет 🌸\n\n"
        f"<b>Сегодня:</b>\n"
        f"💧 Воды: {total_water} мл ({glasses}/8 стаканов)\n"
        f"🍽️ Калории: {total_calories} / {calorie_norm} ккал\n"
        f"😴 Сон: {user.sleep_time} — {user.wake_time}\n"
    )
    
    if user.concerns:
        profile_text += f"\n<b>Беспокоит:</b> {user.concerns}\n"
    
    # Кнопки действий
    keyboard = [
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="progress_show")],
        [InlineKeyboardButton("🍽️ Что я ела", callback_data="food_history")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(profile_text, reply_markup=reply_markup, parse_mode='HTML')
    logger.info(f"User {user.tg_id} viewed profile")


async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает прогресс молодения (график текстом).
    """
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        send_message = query.edit_message_text
        user_id = update.effective_user.id
    else:
        send_message = update.message.reply_text
        user_id = update.effective_user.id
    
    user = get_user(user_id)
    if not user:
        await send_message("Сначала зарегистрируйтесь — /start")
        return
    
    # Имитируем график (в реальном коде здесь будет запрос к БД за историей)
    current_bio = user.bio_age or user.age
    passport_age = user.age
    
    progress_text = (
        f"📊 <b>Мой прогресс молодения</b>\n\n"
        f"Паспортный возраст: {passport_age} лет\n"
        f"Биологический возраст: {current_bio} лет\n"
    )
    
    if current_bio < passport_age:
        diff = passport_age - current_bio
        progress_text += f"\n🎉 <b>Вы молодеете на {diff:.1f} лет!</b>\n"
        progress_text += "График: " + "📉" * int(diff) + "\n"
    elif current_bio > passport_age:
        progress_text += "\n💪 Есть к чему стремиться!\n"
    else:
        progress_text += "\n✨ Отличный старт!\n"
    
    progress_text += (
        "\n<b>Рекомендации:</b>\n"
        "• Продолжайте пить 8 стаканов воды\n"
        "• Делайте скан лица каждый день\n"
        "• Следите за питанием\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile_show")],
        [InlineKeyboardButton("🏠 В меню", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message(progress_text, reply_markup=reply_markup, parse_mode='HTML')
    logger.info(f"User {user.tg_id} viewed progress")
