from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from database import create_user, update_user, get_user
from utils.text_messages import WELCOME
from utils.disclaimers import DISCLAIMER_START

ASK_NAME, ASK_AGE, ASK_HEIGHT, ASK_WEIGHT, ASK_CONCERNS, ASK_WAKE_TIME, ASK_SLEEP_TIME, ASK_FACE_PHOTO, SHOW_DISCLAIMER, ACCEPT = range(10)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал /start"""
    user = update.effective_user
    existing = get_user(user.id)
    
    if existing:
        await update.message.reply_text(
            f"С возвращением, {existing.name}! 🌸\n\n"
            "Используйте главное меню для работы с ботом."
        )
        return ConversationHandler.END
    
    create_user(user.id, username=user.username, first_name=user.first_name)
    
    keyboard = [[InlineKeyboardButton("🌸 Начать регистрацию", callback_data="start_registration")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        WELCOME.format(name=user.first_name),
        reply_markup=reply_markup,
    )
    return SHOW_DISCLAIMER


async def show_disclaimer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показываем дисклеймер"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("✅ Я принимаю", callback_data="accept_disclaimer")],
        [InlineKeyboardButton("❌ Не принимаю", callback_data="decline_disclaimer")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        DISCLAIMER_START,
        reply_markup=reply_markup,
    )
    return ACCEPT


async def accept_disclaimer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь принял дисклеймер"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отлично! Давайте знакомиться. Как вас зовут?")
    return ASK_NAME


async def decline_disclaimer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь отказался"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Жаль 😢 Без согласия мы не можем продолжить. Если передумаете — /start")
    return ConversationHandler.END


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем имя"""
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Имя должно быть минимум 2 буквы. Попробуйте ещё раз:")
        return ASK_NAME
    
    update_user(update.effective_user.id, name=name)
    await update.message.reply_text(f"Приятно познакомиться, {name}! Сколько вам лет?")
    return ASK_AGE


async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем возраст"""
    try:
        age = int(update.message.text.strip())
        if not (18 <= age <= 100):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число от 18 до 100:")
        return ASK_AGE
    
    update_user(update.effective_user.id, age=age)
    await update.message.reply_text("Ваш рост в сантиметрах (например: 165):")
    return ASK_HEIGHT


async def ask_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем рост"""
    try:
        height = int(update.message.text.strip())
        if not (140 <= height <= 220):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число от 140 до 220:")
        return ASK_HEIGHT
    
    update_user(update.effective_user.id, height=height)
    await update.message.reply_text("Ваш вес в килограммах (например: 68):")
    return ASK_WEIGHT


async def ask_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем вес"""
    try:
        weight = float(update.message.text.strip().replace(',', '.'))
        if not (40 <= weight <= 200):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число от 40 до 200:")
        return ASK_WEIGHT
    
    update_user(update.effective_user.id, weight=weight)
    
    keyboard = [
        [InlineKeyboardButton("Морщины", callback_data="concern_wrinkles")],
        [InlineKeyboardButton("Пигментация", callback_data="concern_pigmentation")],
        [InlineKeyboardButton("Отёки", callback_data="concern_swelling")],
        [InlineKeyboardButton("Лишний вес", callback_data="concern_weight")],
        [InlineKeyboardButton("Всё и сразу", callback_data="concern_all")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Что вас больше всего беспокоит? (Можно выбрать несколько, нажимайте по очереди)",
        reply_markup=reply_markup,
    )
    return ASK_CONCERNS


async def ask_concerns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем проблемы (можно несколько)"""
    query = update.callback_query
    await query.answer()
    
    concern = query.data.replace("concern_", "")
    context.user_data.setdefault("concerns", []).append(concern)
    
    selected = ", ".join(context.user_data["concerns"])
    await query.edit_message_text(f"Выбрано: {selected}\\n\\nНажмите ещё или напишите 'готово':")
    return ASK_CONCERNS


async def finish_concerns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь написал 'готово'"""
    concerns = ", ".join(context.user_data.get("concerns", []))
    update_user(update.effective_user.id, concerns=concerns)
    
    await update.message.reply_text("Во сколько вы обычно просыпаетесь? (Например: 07:00)")
    return ASK_WAKE_TIME


async def ask_wake_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем время подъёма"""
    time = update.message.text.strip()
    if not validate_time(time):
        await update.message.reply_text("Формат: ЧЧ:ММ (например 07:00)")
        return ASK_WAKE_TIME
    
    update_user(update.effective_user.id, wake_time=time)
    await update.message.reply_text("Во сколько вы обычно ложитесь спать? (Например: 22:30)")
    return ASK_SLEEP_TIME


async def ask_sleep_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем время сна"""
    time = update.message.text.strip()
    if not validate_time(time):
        await update.message.reply_text("Формат: ЧЧ:ММ (например 22:30)")
        return ASK_SLEEP_TIME
    
    update_user(update.effective_user.id, sleep_time=time)
    await update.message.reply_text(
        "Отлично! Теперь пришлите селфи лица без макияжа при хорошем освещении. "
        "Это ваша точка отсчёта молодости! 📸✨"
    )
    return ASK_FACE_PHOTO


async def ask_face_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем фото лица"""
    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, пришлите именно фото, не текст:")
        return ASK_FACE_PHOTO
    
    photo = update.message.photo[-1]
    update_user(update.effective_user.id, face_photo_id=photo.file_id)
    
    from handlers.face import analyze_face
    await analyze_face(update, context)
    
    await update.message.reply_text(
        "🎉 Регистрация завершена! Теперь я буду с вами каждый день. "
        "Нажмите /menu чтобы открыть главное меню."
    )
    return ConversationHandler.END


def validate_time(time_str):
    """Проверка формата времени"""
    try:
        hour, minute = map(int, time_str.split(':'))
        return 0 <= hour < 24 and 0 <= minute < 60
    except:
        return False


def get_start_handler():
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^/start$"), start)],
        states={
            SHOW_DISCLAIMER: [CallbackQueryHandler(show_disclaimer, pattern="^start_registration$")],
            ACCEPT: [
                CallbackQueryHandler(accept_disclaimer, pattern="^accept_disclaimer$"),
                CallbackQueryHandler(decline_disclaimer, pattern="^decline_disclaimer$"),
            ],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_height)],
            ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            ASK_CONCERNS: [
                CallbackQueryHandler(ask_concerns, pattern="^concern_"),
                MessageHandler(filters.Regex("(?i)^готово$"), finish_concerns),
            ],
            ASK_WAKE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_wake_time)],
            ASK_SLEEP_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sleep_time)],
            ASK_FACE_PHOTO: [MessageHandler(filters.PHOTO, ask_face_photo)],
        },
        fallbacks=[MessageHandler(filters.COMMAND, start)],
        name="registration",
        persistent=True,
    )
