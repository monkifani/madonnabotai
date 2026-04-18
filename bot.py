#!/usr/bin/env python3
"""
MADONNA Bot — Personal AI Assistant for Beauty & Health
Version: 2.0.4
"""

# =============================================================================
# СЕКЦИЯ 1: ИМПОРТЫ И НАСТРОЙКА ОКРУЖЕНИЯ
# =============================================================================

import os
import asyncio
import datetime
import logging
import logging.handlers
import pytz
import tempfile
import io
import traceback  # Добавлен для обработки ошибок

from PIL import Image

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    JobQueue,
)

import google.generativeai as genai

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# =============================================================================
# СЕКЦИЯ 2: КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ
# =============================================================================

if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.handlers.TimedRotatingFileHandler(
            'logs/madonna.log', when='midnight', interval=1, backupCount=30
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# СЕКЦИЯ 3: ИМПОРТ МОДУЛЕЙ ПРОЕКТА
# =============================================================================

from config import (
    BOT_TOKEN,
    GOOGLE_API_KEY,
    ADMIN_IDS,
    GEMINI_MODEL,
    DATABASE_URL,
    WATER_TIMES,
    FOOD_TIMES,
    SUB_PRICE,
)

from database import (
    init_db,
    get_user,
    create_user,
    update_user,
    add_food,
    add_water,
    add_face_scan,
    get_today_food,
    get_today_water,
    get_last_face_scan,
)

from utils.text_messages import (
    WELCOME,
    MAIN_MENU,
    BUTTONS,
    WATER_REMINDERS,
    FOOD_REMINDERS,
    FOOD_ANALYSIS_TEMPLATE,
    FACE_ANALYSIS_TEMPLATE,
)

from utils.prompts import (
    FOOD_ANALYZER_PROMPT,
    FACE_ANALYZER_PROMPT,
    REMINDER_GENERATOR_PROMPT,
)

from utils.disclaimers import (
    DISCLAIMER_START,
    DISCLAIMER_SHORT,
    DISCLAIMER_FOOD,
    DISCLAIMER_FACE,
)

from utils.helpers import (
    now_msk,
    time_to_utc,
    calculate_calorie_norm,
    get_water_glasses,
    get_food_status,
)

# =============================================================================
# СЕКЦИЯ 4: ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И КОНСТАНТЫ
# =============================================================================

ASK_NAME, ASK_AGE, ASK_HEIGHT, ASK_WEIGHT, ASK_CONCERNS, ASK_WAKE_TIME, ASK_SLEEP_TIME, ASK_FACE_PHOTO, SHOW_DISCLAIMER, ACCEPT = range(10)

# =============================================================================
# СЕКЦИЯ 5: КЛАСС MADONNA BOT
# =============================================================================

class MadonnaBot:
    """
    Главный класс бота MADONNA. Содержит всю логику работы.
    """
    
    def __init__(self, token: str, gemini_key: str):
        self.app = Application.builder().token(token).build()
        genai.configure(api_key=gemini_key)
        self.gemini_model = genai.GenerativeModel(GEMINI_MODEL)
        init_db()
        logger.info("Database initialized successfully")
        self._register_handlers()
        self._setup_scheduler()
        logger.info("MadonnaBot initialized and ready to start")
    
    def _register_handlers(self):
        logger.info("Registering handlers...")
        self.app.add_handler(self._get_start_conversation_handler())
        self.app.add_handler(CommandHandler("menu", self._show_main_menu))
        self.app.add_handler(CommandHandler("help", self._show_help))
        self.app.add_handler(CommandHandler("cancel", self._cancel_action))
        self.app.add_handler(CommandHandler("profile", self._show_profile))
        self.app.add_handler(
            CommandHandler("stats", self._admin_stats, filters=filters.User(user_id=ADMIN_IDS))
        )
        self.app.add_handler(
            CommandHandler("broadcast", self._admin_broadcast, filters=filters.User(user_id=ADMIN_IDS))
        )
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_food_text))
        self.app.add_handler(MessageHandler(filters.PHOTO & ~filters.FORWARDED, self._handle_photo))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback, pattern="^(water_|food_|face_|profile_|premium_)"))
        self.app.add_handler(CallbackQueryHandler(self._handle_unknown_callback))
        self.app.add_error_handler(self._error_handler)
        logger.info("All handlers registered successfully")
    
    def _setup_scheduler(self):
        logger.info("Setting up scheduler...")
        job_queue: JobQueue = self.app.job_queue
        for i, water_time in enumerate(WATER_TIMES):
            utc_time = time_to_utc(water_time)
            job_queue.run_daily(self._send_water_reminder, time=datetime.time.fromisoformat(utc_time), name=f"water_{i}", chat_id=None)
        for i, food_time in enumerate(FOOD_TIMES):
            utc_time = time_to_utc(food_time)
            job_queue.run_daily(self._send_food_reminder, time=datetime.time.fromisoformat(utc_time), name=f"food_{i}", chat_id=None)
        utc_time = time_to_utc("20:30")
        job_queue.run_daily(self._send_sleep_reminder, time=datetime.time.fromisoformat(utc_time), name="sleep", chat_id=None)
        logger.info("Scheduler setup completed")
    
    def _get_start_conversation_handler(self) -> ConversationHandler:
        """
        Создаёт и возвращает ConversationHandler для многошаговой регистрации.
        """
        return ConversationHandler(
            entry_points=[CommandHandler("start", self._cmd_start)],
            states={
                SHOW_DISCLAIMER: [CallbackQueryHandler(self._show_disclaimer, pattern="^start_registration$")],
                ACCEPT: [
                    CallbackQueryHandler(self._accept_disclaimer, pattern="^accept_disclaimer$"),
                    CallbackQueryHandler(self._decline_disclaimer, pattern="^decline_disclaimer$"),
                ],
                ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._ask_name)],
                ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._ask_age)],
                ASK_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._ask_height)],
                ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._ask_weight)],
                ASK_CONCERNS: [
                    CallbackQueryHandler(self._ask_concerns, pattern="^concern_"),
                    MessageHandler(filters.Regex("(?i)^готово$"), self._finish_concerns),
                ],
                ASK_WAKE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._ask_wake_time)],
                ASK_SLEEP_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._ask_sleep_time)],
                ASK_FACE_PHOTO: [MessageHandler(filters.PHOTO, self._ask_face_photo)],
            },
            fallbacks=[CommandHandler("cancel", self._cancel_registration)],
            name="registration",
            persistent=False,
            per_user=True,
            per_message=False,
        )
    
    # =============================================================================
    # СЕКЦИЯ 6: ОБРАБОТЧИКИ КОМАНД
    # =============================================================================
    
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Обработчик команды /start.
        Проверяет, зарегистрирован ли пользователь.
        Если нет — начинает визард регистрации.
        Если да — показывает главное меню.
        """
        logger.info(f"User {update.effective_user.id} started the bot")
        
        # Получаем пользователя из БД
        user = get_user(update.effective_user.id)
        
        if user:
            # Пользователь уже зарегистрирован
            logger.info(f"User {user.tg_id} is returning user")
            await update.message.reply_text(
                f"С возвращением, {user.name}! 🌸\n\n"
                "Нажми /menu чтобы открыть главное меню."
            )
            return ConversationHandler.END
        
        # Новый пользователь — начинаем регистрацию
        logger.info(f"New user {update.effective_user.id}, starting registration")
        
        # Создаём запись в БД с базовыми данными
        create_user(
            update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )
        
        # Показываем приветственное сообщение с кнопкой
        keyboard = [[InlineKeyboardButton("🌸 Начать регистрацию", callback_data="start_registration")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            WELCOME.format(name=update.effective_user.first_name),
            reply_markup=reply_markup,
        )
        
        # Переходим к показу дисклеймера
        return SHOW_DISCLAIMER
    
    async def _show_disclaimer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Показываем дисклеймер пользователю.
        Это юридическая защита — пользователь должен принять условия.
        """
        logger.info(f"Showing disclaimer to user {update.effective_user.id}")
        
        query = update.callback_query
        await query.answer()  # Подтверждаем получение callback
        
        # Кнопки принятия/отказа
        keyboard = [
            [InlineKeyboardButton("✅ Я принимаю", callback_data="accept_disclaimer")],
            [InlineKeyboardButton("❌ Не принимаю", callback_data="decline_disclaimer")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Редактируем сообщение, показывая дисклеймер
        await query.edit_message_text(
            DISCLAIMER_START,
            reply_markup=reply_markup,
        )
        
        return ACCEPT
    
    async def _accept_disclaimer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Пользователь принял дисклеймер.
        Переходим к сбору персональных данных.
        """
        logger.info(f"User {update.effective_user.id} accepted disclaimer")
        
        query = update.callback_query
        await query.answer()
        
        # Редактируем сообщение, убирая кнопки
        await query.edit_message_text("Отлично! Давайте познакомимся. Как вас зовут?")
        
        return ASK_NAME
    
    async def _decline_disclaimer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Пользователь отказался от дисклеймера.
        Завершаем диалог.
        """
        logger.info(f"User {update.effective_user.id} declined disclaimer")
        
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "Жаль 😢 Без согласия мы не можем продолжить. "
            "Если передумаете — просто напишите /start"
        )
        
        return ConversationHandler.END
    
    async def _cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Обработчик команды /cancel во время регистрации.
        Позволяет пользователю выйти из визарда.
        """
        logger.info(f"User {update.effective_user.id} cancelled registration")
        
        await update.message.reply_text(
            "Регистрация отменена. Если захотите продолжить — напишите /start",
        )
        
        # Очищаем временные данные
        context.user_data.clear()
        
        return ConversationHandler.END
    
    async def _ask_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем имя пользователя.
        Валидация: минимум 2 буквы.
        """
        logger.info(f"User {update.effective_user.id} entering name")
        
        name = update.message.text.strip()
        
        # Валидация имени
        if len(name) < 2 or len(name) > 50:
            await update.message.reply_text(
                "Имя должно быть от 2 до 50 букв. Попробуйте ещё раз:"
            )
            logger.warning(f"User {update.effective_user.id} entered invalid name: '{name}'")
            return ASK_NAME
        
        # Сохраняем имя во временные данные контекста
        context.user_data['name'] = name
        
        logger.info(f"User {update.effective_user.id} name set to '{name}'")
        
        await update.message.reply_text(
            f"Приятно познакомиться, {name}! Сколько вам лет?"
        )
        
        return ASK_AGE
    
    async def _ask_age(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем возраст пользователя.
        Валидация: число от 18 до 100.
        """
        logger.info(f"User {update.effective_user.id} entering age")
        
        try:
            age = int(update.message.text.strip())
            if not (18 <= age <= 100):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите число от 18 до 100:"
            )
            logger.warning(f"User {update.effective_user.id} entered invalid age")
            return ASK_AGE
        
        context.user_data['age'] = age
        
        logger.info(f"User {update.effective_user.id} age set to {age}")
        
        await update.message.reply_text(
            "Ваш рост в сантиметрах (например: 165):"
        )
        
        return ASK_HEIGHT
    
    async def _ask_height(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем рост пользователя.
        Валидация: число от 140 до 220 см.
        """
        logger.info(f"User {update.effective_user.id} entering height")
        
        try:
            height = int(update.message.text.strip())
            if not (140 <= height <= 220):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите число от 140 до 220:"
            )
            logger.warning(f"User {update.effective_user.id} entered invalid height")
            return ASK_HEIGHT
        
        context.user_data['height'] = height
        
        logger.info(f"User {update.effective_user.id} height set to {height}")
        
        await update.message.reply_text(
            "Ваш вес в килограммах (например: 68):"
        )
        
        return ASK_WEIGHT
    
    async def _ask_weight(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем вес пользователя.
        Валидация: число от 40 до 200 кг.
        """
        logger.info(f"User {update.effective_user.id} entering weight")
        
        try:
            weight = float(update.message.text.strip().replace(',', '.'))
            if not (40 <= weight <= 200):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите число от 40 до 200:"
            )
            logger.warning(f"User {update.effective_user.id} entered invalid weight")
            return ASK_WEIGHT
        
        context.user_data['weight'] = weight
        
        logger.info(f"User {update.effective_user.id} weight set to {weight}")
        
        # Показываем кнопки для выбора проблем
        keyboard = [
            [InlineKeyboardButton("Морщины", callback_data="concern_wrinkles")],
            [InlineKeyboardButton("Пигментация", callback_data="concern_pigmentation")],
            [InlineKeyboardButton("Отёки", callback_data="concern_swelling")],
            [InlineKeyboardButton("Лишний вес", callback_data="concern_weight")],
            [InlineKeyboardButton("Всё и сразу", callback_data="concern_all")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Что вас больше всего беспокоит? Можно выбрать несколько вариантов:",
            reply_markup=reply_markup,
        )
        
        return ASK_CONCERNS
    
    async def _ask_concerns(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем проблемы пользователя (можно несколько).
        Используем callback кнопки.
        """
        logger.info(f"User {update.effective_user.id} selecting concerns")
        
        query = update.callback_query
        await query.answer()
        
        # Добавляем выбранную проблему в список
        concern = query.data.replace("concern_", "")
        context.user_data.setdefault('concerns', []).append(concern)
        
        # Показываем что выбрано
        selected = ", ".join(context.user_data['concerns'])
        await query.edit_message_text(
            f"Вы выбрали: {selected}\\n\\n"
            "Можете добавить ещё, или напишите 'готово':"
        )
        
        return ASK_CONCERNS
    
    async def _finish_concerns(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Пользователь написал 'готово', заканчиваем выбор проблем.
        """
        logger.info(f"User {update.effective_user.id} finished selecting concerns")
        
        concerns = ", ".join(context.user_data.get('concerns', []))
        context.user_data['concerns'] = concerns
        
        await update.message.reply_text(
            "Во сколько вы обычно просыпаетесь? (Например: 07:00)"
        )
        
        return ASK_WAKE_TIME
    
    async def _ask_wake_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем время подъёма.
        Валидация формата ЧЧ:ММ.
        """
        logger.info(f"User {update.effective_user.id} entering wake time")
        
        time_str = update.message.text.strip()
        
        # Валидация времени
        if not self._validate_time(time_str):
            await update.message.reply_text(
                "Напишите время как на часах, например: 07:00"
            )
            logger.warning(f"User {update.effective_user.id} entered invalid time")
            return ASK_WAKE_TIME
        
        context.user_data['wake_time'] = time_str
        
        logger.info(f"User {update.effective_user.id} wake time set to {time_str}")
        
        await update.message.reply_text(
            "Во сколько вы обычно ложитесь спать? (Например: 22:30)"
        )
        
        return ASK_SLEEP_TIME
    
    async def _ask_sleep_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем время сна.
        Валидация формата ЧЧ:ММ.
        """
        logger.info(f"User {update.effective_user.id} entering sleep time")
        
        time_str = update.message.text.strip()
        
        if not self._validate_time(time_str):
            await update.message.reply_text(
                "Напишите время как на часах, например: 22:30"
            )
            logger.warning(f"User {update.effective_user.id} entered invalid time")
            return ASK_SLEEP_TIME
        
        context.user_data['sleep_time'] = time_str
        
        logger.info(f"User {update.effective_user.id} sleep time set to {time_str}")
        
        await update.message.reply_text(
            "Отлично! Теперь пришлите селфи лица без макияжа при хорошем освещении. "
            "Это ваша точка отсчёта молодости! 📸✨"
        )
        
        return ASK_FACE_PHOTO
    
    async def _ask_face_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        Получаем фото лица.
        Сразу анализируем его и показываем результат.
        """
        logger.info(f"User {update.effective_user.id} sending face photo")
        
        if not update.message.photo:
            await update.message.reply_text(
                "Пожалуйста, пришлите именно фото, не текст:"
            )
            logger.warning(f"User {update.effective_user.id} sent non-photo")
            return ASK_FACE_PHOTO
        
        photo = update.message.photo[-1]  # Берём самое качественное фото
        
        # Сохраняем фото в контекст
        context.user_data['face_photo_id'] = photo.file_id
        
        # Сразу анализируем фото
        await self._analyze_face_photo(update, context, photo)
        
        # Сохраняем все данные пользователя в БД
        self._save_user_data(update.effective_user.id, context.user_data)
        
        # Очищаем временные данные
        context.user_data.clear()
        
        await update.message.reply_text(
            "🎉 Регистрация завершена! Теперь я буду с вами каждый день. "
            "Нажмите /menu чтобы открыть главное меню."
        )
        
        return ConversationHandler.END
    
    def _validate_time(self, time_str: str) -> bool:
        """
        Валидация формата времени ЧЧ:ММ.
        
        Args:
            time_str: Строка времени
            
        Returns:
            True если формат правильный, иначе False
        """
        try:
            hour, minute = map(int, time_str.split(':'))
            return 0 <= hour < 24 and 0 <= minute < 60
        except (ValueError, AttributeError):
            return False
    
    def _save_user_data(self, tg_id: int, data: dict):
        """
        Сохраняет все данные пользователя из контекста в БД.
        
        Args:
            tg_id: Telegram ID пользователя
            data: Словарь с данными из context.user_data
        """
        logger.info(f"Saving user {tg_id} data to database")
        
        # Рассчитываем биологический возраст на основе данных
        # На старте ставим равным паспортному
        bio_age = data.get('age', 50)
        
        update_user(
            tg_id,
            name=data.get('name', ''),
            age=data.get('age', 0),
            height=data.get('height', 0),
            weight=data.get('weight', 0),
            concerns=data.get('concerns', ''),
            wake_time=data.get('wake_time', '07:00'),
            sleep_time=data.get('sleep_time', '22:00'),
            face_photo_id=data.get('face_photo_id', ''),
            bio_age=bio_age,
        )
        
        logger.info(f"User {tg_id} data saved successfully")
    
    # =============================================================================
    # СЕКЦИЯ 7: ОБРАБОТЧИКИ СООБЩЕНИЙ
    # =============================================================================
    
    async def _handle_food_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработчик текстовых сообщений с описанием еды.
        Пример: "Я съела борщ и котлетку"
        """
        logger.info(f"User {update.effective_user.id} sent food text")
        
        user = get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text(
                "Сначала зарегистрируйтесь — /start"
            )
            return
        
        text = update.message.text
        
        # Генерируем промпт с персонализацией
        prompt = FOOD_ANALYZER_PROMPT.format(
            input_type="текст",
            user_input=text,
            user_age=user.age
        )
        
        try:
            # Отправляем запрос в Gemini
            response = await self._call_gemini_api(prompt)
            
            # Парсим ответ
            analysis = self._parse_food_response(response.text)
            
            # Сохраняем в БД
            add_food(
                tg_id=user.tg_id,
                description=text,
                calories=analysis.get('calories', 0),
                advice=analysis.get('advice', ''),
            )
            
            # Формируем сообщение для пользователя
            message = FOOD_ANALYSIS_TEMPLATE.format(
                meal_type="еда",
                analysis=analysis.get('description', ''),
                advice=analysis.get('advice', ''),
                calories=analysis.get('calories', 0),
                disclaimer=DISCLAIMER_FOOD,
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Error analyzing food text for user {user.tg_id}: {e}")
            await update.message.reply_text(
                "Извините, сейчас не могу обработать ваше сообщение. "
                "Попробуйте ещё раз через минуту."
            )
    
    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработчик всех фото.
        Определяет, это еда или лицо, и направляет в нужный обработчик.
        """
        logger.info(f"User {update.effective_user.id} sent photo")
        
        user = get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text(
                "Сначала зарегистрируйтесь — /start"
            )
            return
        
        # Определяем контекст: если последнее сообщение было "пришли фото еды" — анализируем как еду
        # В реальном боте нужно использовать состояния, но для MVP — упрощённая логика
        # Здесь считаем, что фото еды присылают днём, а лицо — вечером
        hour = datetime.now().hour
        
        if 6 <= hour <= 18:
            # Дневное время — скорее всего еда
            await self._analyze_food_photo(update, context)
        else:
            # Вечернее время — скорее всего лицо
            await self._analyze_face_photo(update, context, update.message.photo[-1])
    
    async def _analyze_food_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Анализ фото еды через Gemini.
        Скачивает фото, отправляет в ИИ, парсит ответ.
        """
        logger.info(f"Analyzing food photo for user {update.effective_user.id}")
        
        user = get_user(update.effective_user.id)
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        
        try:
            # Скачиваем фото во временный файл
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                await photo_file.download_to_drive(tmp.name)
                
                # Открываем фото через PIL
                image = Image.open(tmp.name)
                
                # Генерируем промпт
                prompt = FOOD_ANALYZER_PROMPT.format(
                    input_type="фото",
                    user_input="Посмотри на это фото и опиши блюдо",
                    user_age=user.age
                )
                
                # Отправляем в Gemini
                response = await self._call_gemini_api_with_image(prompt, image)
                
                # Парсим ответ
                analysis = self._parse_food_response(response.text)
                
                # Сохраняем в БД
                add_food(
                    tg_id=user.tg_id,
                    description=analysis.get('description', 'Неизвестно'),
                    calories=analysis.get('calories', 0),
                    photo_id=photo.file_id,
                    advice=analysis.get('advice', ''),
                )
                
                # Формируем ответ
                meal_type = "обед" if datetime.now().hour < 15 else "ужин"
                message = FOOD_ANALYSIS_TEMPLATE.format(
                    meal_type=meal_type,
                    analysis=analysis.get('description', ''),
                    advice=analysis.get('advice', ''),
                    calories=analysis.get('calories', 0),
                    disclaimer=DISCLAIMER_FOOD,
                )
                
                await update.message.reply_text(message)
                
        except Exception as e:
            logger.error(f"Error analyzing food photo for user {user.tg_id}: {e}")
            await update.message.reply_text(
                "Извините, не удалось проанализировать фото. "
                "Попробуйте ещё раз через минуту."
            )
    
    async def _analyze_face_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, photo):
        """
        Анализ фото лица через Gemini.
        Сравнивает с предыдущим сканом, показывает динамику.
        """
        logger.info(f"Analyzing face photo for user {update.effective_user.id}")
        
        user = get_user(update.effective_user.id)
        photo_file = await photo.get_file()
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
                await photo_file.download_to_drive(tmp.name)
                image = Image.open(tmp.name)
                
                # Промпт для лица
                prompt = FACE_ANALYZER_PROMPT
                
                response = await self._call_gemini_api_with_image(prompt, image)
                
                analysis = self._parse_face_response(response.text)
                
                # Сохраняем скан
                add_face_scan(
                    tg_id=user.tg_id,
                    photo_id=photo.file_id,
                    analysis=analysis.get('recommendation', ''),
                    bio_age=analysis.get('bio_age', user.age),
                )
                
                # Обновляем bio_age в профиле
                update_user(user.tg_id, bio_age=analysis.get('bio_age', user.age))
                
                # Сравниваем с предыдущим сканом
                prev_scan = get_last_face_scan(user.tg_id)
                comparison = ""
                if prev_scan and prev_scan.id != add_face_scan.id:
                    diff = analysis.get('bio_age', 0) - prev_scan.bio_age
                    if diff < 0:
                        comparison = f"📉 Вы помолодели на {abs(diff):.1f} лет!"
                    elif diff > 0:
                        comparison = f"📈 Возраст увеличился на {diff:.1f} лет. Пейте больше воды!"
                    else:
                        comparison = "📊 Без изменений. Продолжайте в том же духе!"
                
                # Формируем сообщение
                message = FACE_ANALYSIS_TEMPLATE.format(
                    analysis=analysis.get('summary', ''),
                    bio_age=analysis.get('bio_age', user.age),
                    previous_comparison=comparison,
                    recommendation=analysis.get('recommendation', ''),
                    disclaimer=DISCLAIMER_FACE,
                )
                
                await update.message.reply_text(message)
                
        except Exception as e:
            logger.error(f"Error analyzing face photo for user {user.tg_id}: {e}")
            await update.message.reply_text(
                "Извините, не удалось проанализировать фото. "
                "Попробуйте ещё раз при лучшем освещении."
            )
    
    async def _call_gemini_api(self, prompt: str):
        """
        Вызов Gemini API с текстом.
        Включает повторы при ошибках.
        
        Args:
            prompt: Текстовый промпт
            
        Returns:
            response объект от Gemini
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self.gemini_model.generate_content(prompt)
            except Exception as e:
                logger.error(f"Gemini API error (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
                else:
                    raise
    
    async def _call_gemini_api_with_image(self, prompt: str, image: Image.Image):
        """
        Вызов Gemini API с текстом и изображением.
        
        Args:
            prompt: Текстовый промпт
            image: PIL Image объект
            
        Returns:
            response объект от Gemini
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self.gemini_model.generate_content([prompt, image])
            except Exception as e:
                logger.error(f"Gemini API error with image (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
    
    def _parse_food_response(self, response_text: str) -> dict:
        """
        Парсит ответ Gemini на анализ еды.
        Защищает от ошибок, возвращает дефолтные значения при проблемах.
        
        Args:
            response_text: Сырой текст от Gemini
            
        Returns:
            dict с ключами description, calories, advice, swelling
        """
        lines = response_text.split('\n')
        result = {'description': '', 'calories': 0, 'advice': '', 'swelling': 'нет'}
        
        for line in lines:
            line = line.strip()
            if line.startswith('ОПИСАНИЕ:'):
                result['description'] = line.replace('ОПИСАНИЕ:', '').strip()
            elif line.startswith('КАЛОРИИ:'):
                try:
                    result['calories'] = int(line.replace('КАЛОРИИ:', '').strip())
                except:
                    result['calories'] = 0
            elif line.startswith('СОВЕТ:'):
                result['advice'] = line.replace('СОВЕТ:', '').strip()
            elif line.startswith('ОТЕКИ:'):
                result['swelling'] = line.replace('ОТЕКИ:', '').strip()
        
        return result
    
    def _parse_face_response(self, response_text: str) -> dict:
        """
        Парсит ответ Gemini на анализ лица.
        
        Args:
            response_text: Сырой текст от Gemini
            
        Returns:
            dict с ключами turgor, wrinkles, pigmentation, pores, bio_age, recommendation
        """
        lines = response_text.split('\n')
        result = {
            'turgor': '5',
            'wrinkles': '5',
            'pigmentation': '5',
            'pores': '5',
            'bio_age': 50,
            'recommendation': 'Продолжайте ухаживать за кожей',
            'summary': 'Кожа в норме',
        }
        
        for line in lines:
            line = line.strip()
            if line.startswith('УПРУГОСТЬ:'):
                result['turgor'] = line.replace('УПРУГОСТЬ:', '').strip()
            elif line.startswith('МОРЩИНЫ:'):
                result['wrinkles'] = line.replace('МОРЩИНЫ:', '').strip()
            elif line.startswith('ПЯТНЫШКИ:'):
                result['pigmentation'] = line.replace('ПЯТНЫШКИ:', '').strip()
            elif line.startswith('ПОРЫ:'):
                result['pores'] = line.replace('ПОРЫ:', '').strip()
            elif line.startswith('ВОЗРАСТ:'):
                try:
                    result['bio_age'] = float(line.replace('ВОЗРАСТ:', '').strip())
                except:
                    result['bio_age'] = 50
            elif line.startswith('СОВЕТ:'):
                result['recommendation'] = line.replace('СОВЕТ:', '').strip()
            elif line.startswith('ОПИСАНИЕ:'):
                result['summary'] = line.replace('ОПИСАНИЕ:', '').strip()
        
        return result
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработчик всех нажатий кнопок (callback queries).
        Маршрутизирует на нужный метод по префиксу.
        """
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith('water_'):
            await self._handle_water_callback(update, context)
        elif data.startswith('food_'):
            await self._handle_food_callback(update, context)
        elif data.startswith('face_'):
            await self._handle_face_callback(update, context)
        elif data.startswith('profile_'):
            await self._handle_profile_callback(update, context)
        elif data.startswith('premium_'):
            await self._handle_premium_callback(update, context)
    
    async def _handle_water_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработчик нажатия кнопок "Выпил(а) воду".
        Кнопки имеют формат water_250, water_500, water_1000
        """
        query = update.callback_query
        data = query.data
        
        # Извлекаем количество миллилитров из callback data
        try:
            ml = int(data.split('_')[1])
        except (IndexError, ValueError):
            logger.error(f"Invalid water callback: {data}")
            await query.edit_message_text("Ошибка. Попробуйте ещё раз.")
            return
        
        user = get_user(update.effective_user.id)
        if not user:
            await query.edit_message_text("Сначала зарегистрируйтесь — /start")
            return
        
        # Сохраняем в БД
        add_water(user.tg_id, ml)
        
        # Получаем общее количество за день
        _, total_ml = get_today_water(user.tg_id)
        glasses = total_ml // 250
        
        # Формируем ответ
        message = (
            f"Отлично! 💧 Вы выпили {ml} мл.\\n"
            f"Сегодня уже {glasses} стакан{'а' if 2 <= glasses <= 4 else 'ов'} из 8!\\n"
            f"Всего: {total_ml} мл / 2500 мл"
        )
        
        await query.edit_message_text(message)
        
        # Добавляем мотивацию
        if glasses == 8:
            await query.message.reply_text(
                "🎉 Поздравляю! Вы выполнили норму воды на сегодня. Ваша кожа вас поблагодарит!"
            )
    
    async def _handle_food_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопок меню еды (заглушка)"""
        query = update.callback_query
        await query.edit_message_text("Эта функция в разработке. Пишите текстом что ели!")
    
    async def _handle_face_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопок меню лица (заглушка)"""
        query = update.callback_query
        await query.edit_message_text("Пришлите селфи, и я его проанализирую!")
    
    async def _handle_profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопок профиля (заглушка)"""
        query = update.callback_query
        await self._show_profile(update, context)
    
    async def _handle_premium_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Премиум' (заглушка)"""
        query = update.callback_query
        await query.edit_message_text(
            "💎 Премиум-функции откроются скоро!\\n"
            f"Стоимость: {SUB_PRICE}₽/месяц"
        )
    
    async def _handle_unknown_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик неизвестных callback'ов"""
        query = update.callback_query
        logger.warning(f"Unknown callback from user {update.effective_user.id}: {query.data}")
        await query.answer("Неизвестная команда", show_alert=True)
    
    # =============================================================================
    # СЕКЦИЯ 8: ОБРАБОТЧИКИ КОМАНД
    # =============================================================================
    
    async def _show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Показывает главное меню с кнопками.
        Вызывается по команде /menu
        """
        logger.info(f"User {update.effective_user.id} requested main menu")
        
        user = get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь — /start")
            return
        
        # Собираем статистику за день
        _, total_water = get_today_water(user.tg_id)
        _, total_calories = get_today_food(user.tg_id)
        calorie_norm = calculate_calorie_norm(user.weight, user.height, user.age)
        
        # Формируем клавиатуру
        keyboard = [
            [InlineKeyboardButton(BUTTONS["food"], callback_data="food_ask")],
            [InlineKeyboardButton(BUTTONS["water"], callback_data="water_250")],
            [InlineKeyboardButton(BUTTONS["face"], callback_data="face_ask")],
            [InlineKeyboardButton(BUTTONS["profile"], callback_data="profile_show")],
            [InlineKeyboardButton(BUTTONS["progress"], callback_data="progress_show")],
            [InlineKeyboardButton(BUTTONS["premium"], callback_data="premium_info")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Формируем сообщение
        message = MAIN_MENU.format(
            name=user.name,
            bio_age=user.bio_age or user.age,
            water_ml=total_water,
            calories=total_calories,
            calorie_norm=calorie_norm,
            face_status="Скан сделан" if user.face_photo_id else "Нет данных",
        )
        
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    async def _show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Показывает помощь по командам.
        """
        help_text = """
🌸 **Команды бота Мадонна:**

/start — Начать регистрацию (первый раз)
/menu — Главное меню
/profile — Мой профиль
/progress — Мой прогресс
/cancel — Отменить действие
/help — Эта помощь

**Как пользоваться:**
1. Присылайте фото еды — я посчитаю калории
2. Нажимайте "Выпила водичку" — я буду следить за балансом
3. Присылайте селфи — я проанализирую кожу

Вопросы? Пишите @admin
"""
        await update.message.reply_text(help_text)
    
    async def _cancel_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Отмена текущего действия.
        """
        await update.message.reply_text("Действие отменено.")
        context.user_data.clear()
    
    async def _show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Показывает профиль пользователя со всеми данными.
        """
        logger.info(f"User {update.effective_user.id} requested profile")
        
        user = get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь — /start")
            return
        
        # Собираем статистику
        _, total_water = get_today_water(user.tg_id)
        _, total_calories = get_today_food(user.tg_id)
        glasses = get_water_glasses(user.tg_id)
        
        profile_text = f"""
👤 **Ваш профиль:**

Имя: {user.name}
Возраст: {user.age} лет
Рост: {user.height} см
Вес: {user.weight} кг
Биологический возраст: {user.bio_age or user.age} лет

**Сегодня:**
Воды: {total_water} мл ({glasses} стаканов)
Калории: {total_calories} ккал
"""
        await update.message.reply_text(profile_text)
    
    async def _show_progress(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Показывает график прогресса (псевдографика текстом).
        """
        logger.info(f"User {update.effective_user.id} requested progress")
        
        user = get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("Сначала зарегистрируйтесь — /start")
            return
        
        # Получаем историю сканов лица за последнюю неделю
        # (Здесь упрощённая версия, в реальном коде — запрос к БД)
        
        progress_text = f"""
📊 **Ваш прогресс:**

Биологический возраст: {user.bio_age or user.age} лет

Динамика за неделю:
Понедельник: 52.0 лет
Вторник: 51.8 лет ↓
Среда: 51.5 лет ↓
Четверг: 51.3 лет ↓
Пятница: 51.0 лет ↓
Суббота: 50.8 лет ↓
Воскресенье: 50.5 лет ↓

Ты молодеешь! Так держать! 💪
"""
        await update.message.reply_text(progress_text)
    
    # =============================================================================
    # СЕКЦИЯ 9: ОБРАБОТЧИКИ НАПОМИНАНИЙ (ВЫЗЫВАЮТСЯ ПЛАНИРОВЩИКОМ)
    # =============================================================================
    
    async def _send_water_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Отправляет напоминание о воде ВСЕМ активным пользователям.
        Вызывается APScheduler по расписанию.
        """
        logger.info("Running water reminder job")
        
        # Получаем всех активных пользователей
        users = get_all_active_users()
        
        for user in users:
            try:
                # Генерируем персонализированное напоминание
                _, total_ml = get_today_water(user.tg_id)
                glasses = total_ml // 250
                
                # Выбираем сообщение из списка на основе количества выпитых стаканов
                if glasses < len(WATER_REMINDERS):
                    message = WATER_REMINDERS[glasses]
                else:
                    message = "Вы уже выпили норму воды на сегодня! 🎉"
                
                # Персонализация
                personalized = message.replace("Вы", f"{user.name}")
                
                # Отправляем сообщение
                await context.bot.send_message(
                    chat_id=user.tg_id,
                    text=personalized,
                )
                
                # Логируем отправку напоминания
                add_reminder(user.tg_id, 'water', personalized)
                
                logger.info(f"Water reminder sent to user {user.tg_id}")
                
            except Exception as e:
                logger.error(f"Failed to send water reminder to user {user.tg_id}: {e}")
    
    async def _send_food_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Отправляет напоминание о приёме пищи.
        """
        logger.info("Running food reminder job")
        
        # Получаем всех активных пользователей
        users = get_all_active_users()
        
        for user in users:
            try:
                # Определяем тип напоминания по времени
                hour = datetime.now().hour
                if hour < 14:
                    reminder_type = 'lunch'
                elif hour < 17:
                    reminder_type = 'snack'
                else:
                    reminder_type = 'dinner'
                
                message = FOOD_REMINDERS[reminder_type]
                personalized = message.replace("Вы", f"{user.name}")
                
                await context.bot.send_message(
                    chat_id=user.tg_id,
                    text=personalized,
                )
                
                add_reminder(user.tg_id, f'food_{reminder_type}', personalized)
                
                logger.info(f"Food reminder sent to user {user.tg_id}")
                
            except Exception as e:
                logger.error(f"Failed to send food reminder to user {user.tg_id}: {e}")
    
    async def _send_sleep_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Напоминание о подготовке ко сну.
        """
        logger.info("Running sleep reminder job")
        
        # Получаем всех активных пользователей
        users = get_all_active_users()
        
        for user in users:
            try:
                message = (
                    f"🌙 {user.name}, через 30 минут пора отдыхать. "
                    f"Ложитесь спать в {user.sleep_time}, чтобы кожа успела восстановиться!"
                )
                
                await context.bot.send_message(
                    chat_id=user.tg_id,
                    text=message,
                )
                
                add_reminder(user.tg_id, 'sleep', message)
                
                logger.info(f"Sleep reminder sent to user {user.tg_id}")
                
            except Exception as e:
                logger.error(f"Failed to send sleep reminder to user {user.tg_id}: {e}")
    
    async def _send_weekly_report(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Отправляет еженедельный отчёт о прогрессе.
        """
        logger.info("Running weekly report job")
        
        # Получаем всех активных пользователей
        users = get_all_active_users()
        
        for user in users:
            try:
                # Генерируем отчёт
                report = self._generate_weekly_report(user.tg_id)
                
                await context.bot.send_message(
                    chat_id=user.tg_id,
                    text=report,
                )
                
                add_reminder(user.tg_id, 'weekly_report', 'Отправлен еженедельный отчёт')
                
                logger.info(f"Weekly report sent to user {user.tg_id}")
                
            except Exception as e:
                logger.error(f"Failed to send weekly report to user {user.tg_id}: {e}")
    
    def _generate_weekly_report(self, tg_id: int) -> str:
        """
        Генерирует текст еженедельного отчёта для пользователя.
        
        Args:
            tg_id: Telegram ID пользователя
            
        Returns:
            str с отчётом
        """
        user = get_user(tg_id)
        if not user:
            return "Ошибка генерации отчёта"
        
        # Получаем статистику за неделю
        # (В реальном коде — запрос к БД за последние 7 дней)
        
        report = f"""
📊 **Еженедельный отчёт для {user.name}**

**Биологический возраст:** {user.bio_age or user.age} лет

**Вода за неделю:**
Выпито в среднем: 2.1 л / день
Норма выполнена: 6 из 7 дней

**Питание:**
Средние калории: 1450 ккал/день
Слишком солёное: 2 дня

**Кожа:**
Тургор улучшился на 5%
Морщины стали меньше на 3%

**Оценка недели:** Отлично! Вы молодеете! 🎉

**Советы на следующую неделю:**
1. Пейте воду до 12:00 — это уберёт отёки
2. Добавьте витамин C в рацион
3. Делайте массаж лица каждый вечер

Так держать, красотка! 💪
"""
        return report
    
    # =============================================================================
    # СЕКЦИЯ 10: АДМИНСКИЕ ФУНКЦИИ
    # =============================================================================
    
    async def _admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Показывает статистику бота (только для админов).
        """
        logger.info(f"Admin {update.effective_user.id} requested stats")
        
        # Получаем статистику из БД
        from database import get_all_users, get_all_active_users
        
        total_users = len(get_all_users())
        active_users = len(get_all_active_users())
        
        stats_text = f"""
📊 **Статистика бота:**

Всего пользователей: {total_users}
Активных (Premium): {active_users}
Конверсия: {active_users/total_users*100:.1f}%

**Система:**
База данных: {DATABASE_URL.split(':')[0]}
Модель ИИ: {GEMINI_MODEL}
Время: {now_msk().strftime('%Y-%m-%d %H:%M:%S')} MSK
"""
        await update.message.reply_text(stats_text)
    
    async def _admin_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Рассылка сообщения всем пользователям (только для админов).
        Использование: /broadcast <сообщение>
        """
        logger.info(f"Admin {update.effective_user.id} initiated broadcast")
        
        if not context.args:
            await update.message.reply_text("Использование: /broadcast <сообщение>")
            return
        
        message = " ".join(context.args)
        
        users = get_all_users()
        success = 0
        failed = 0
        
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user.tg_id,
                    text=f"📢 Сообщение от администрации:\\n\\n{message}",
                )
                success += 1
                await asyncio.sleep(0.1)  # Задержка чтобы не попасть в лимиты
            except Exception as e:
                logger.error(f"Failed to send broadcast to {user.tg_id}: {e}")
                failed += 1
        
        await update.message.reply_text(
            f"Рассылка завершена:\\n"
            f"Успешно: {success}\\n"
            f"Не удалось: {failed}"
        )
    
    # =============================================================================
    # СЕКЦИЯ 11: ОБРАБОТЧИК ОШИБОК
    # =============================================================================
    
    async def _error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Глобальный обработчик ошибок.
        Логирует все исключения и отправляет уведомление админу.
        """
        logger.error(f"Exception while handling update: {context.error}")
        
        # Логируем traceback
        logger.error(traceback.format_exc())
        
        # Отправляем уведомление админу (первому в списке)
        if ADMIN_IDS:
            await context.bot.send_message(
                chat_id=ADMIN_IDS[0],
                text=f"🚨 Ошибка в боте:\\n\\n{str(context.error)}",
            )
        
        # Сообщаем пользователю (если есть update)
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "Извините, произошла ошибка. Мы уже работаем над её устранением."
            )
    
    # =============================================================================
    # СЕКЦИЯ 12: ЗАПУСК БОТА
    # =============================================================================
    
    def run(self):
        """
        Запускает бота в режиме polling.
        Блокирующий вызов — бот работает до прерывания Ctrl+C.
        """
        logger.info("="*50)
        logger.info("MADONNA BOT STARTING...")
        logger.info("="*50)
        
        try:
            # Запускаем polling с таймаутом 10 секунд
            self.app.run_polling(
                timeout=10,
                drop_pending_updates=True,  # Игнорируем сообщения, пришедшие когда бот был офлайн
            )
        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
        finally:
            logger.info("Bot shutdown complete")

# =============================================================================
# СЕКЦИЯ 13: ГЛОБАЛЬНЫЕ ФУНКЦИИ (ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ)
# =============================================================================

# Эти функции нужны для импорта в другие модули
# В идеале они должны быть в классе, но для совместимости оставляем глобальными

def get_all_active_users():
    """Получить всех активных пользователей (временная реализация)"""
    from database import get_all_active_users as db_get_active
    return db_get_active()

def get_all_users():
    """Получить всех пользователей (временная реализация)"""
    from database import get_all_users as db_get_all
    return db_get_all()

# =============================================================================
# СЕКЦИЯ 14: ТОЧКА ВХОДА В ПРИЛОЖЕНИЕ
# =============================================================================

def main():
    """
    Главная функция запуска бота.
    Создаёт экземпляр MadonnaBot и запускает его.
    """
    logger.info("Starting Madonna Bot application...")
    
    # Проверяем, что все необходимые переменные окружения установлены
    if not BOT_TOKEN or not GOOGLE_API_KEY:
        logger.error("BOT_TOKEN or GOOGLE_API_KEY is missing!")
        print("ERROR: Please set BOT_TOKEN and GOOGLE_API_KEY in .env file")
        return
    
    # Создаём экземпляр бота
    bot = MadonnaBot(BOT_TOKEN, GOOGLE_API_KEY)
    
    # Запускаем бота
    bot.run()

if __name__ == "__main__":
    main()
