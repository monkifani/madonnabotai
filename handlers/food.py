from telegram import Update
from telegram.ext import ContextTypes
from database import add_food, get_user
from utils.prompts import FOOD_ANALYZER_PROMPT
from utils.text_messages import FOOD_ANALYSIS_TEMPLATE
from utils.disclaimers import DISCLAIMER_FOOD
from config import GOOGLE_API_KEY, GEMINI_MODEL
import google.generativeai as genai
from datetime import datetime

genai.configure(api_key=GOOGLE_API_KEY)


async def handle_food_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь прислал фото еды"""
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйся — /start")
        return
    
    photo = update.message.photo[-1]
    photo_file = await photo.get_file()
    
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
        await photo_file.download_to_drive(tmp.name)
        
        model = genai.GenerativeModel(GEMINI_MODEL)
        
        # Подставляем возраст пользователя для персонификации
        prompt = FOOD_ANALYZER_PROMPT.format(
            input_type="фото",
            user_input="Посмотри на это фото и опиши блюдо",
            user_age=user.age
        )
        
        from PIL import Image
        image = Image.open(tmp.name)
        response = model.generate_content([prompt, image])
        
    # Парсим детальный ответ
    analysis = parse_food_response(response.text)
    
    # Сохраняем в БД
    add_food(
        tg_id=user.tg_id,
        description=analysis.get('description', 'Неизвестно'),
        calories=analysis.get('calories', 0),
        photo_id=photo.file_id,
        advice=analysis.get('advice', ''),
    )
    
    # Формируем ответ для пользователя
    meal_type = "обед" if datetime.now().hour < 15 else "ужин"
    
    message = FOOD_ANALYSIS_TEMPLATE.format(
        meal_type=meal_type,
        analysis=analysis.get('description', ''),
        advice=analysis.get('advice', ''),
        calories=analysis.get('calories', 0),
        disclaimer=DISCLAIMER_FOOD,
    )
    
    await update.message.reply_text(message)


async def handle_food_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь написал текстом что ел"""
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйся — /start")
        return
    
    text = update.message.text
    
    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = FOOD_ANALYZER_PROMPT.format(
        input_type="текст",
        user_input=text,
        user_age=user.age
    )
    
    response = model.generate_content(prompt)
    analysis = parse_food_response(response.text)
    
    add_food(
        tg_id=user.tg_id,
        description=text,
        calories=analysis.get('calories', 0),
        advice=analysis.get('advice', ''),
    )
    
    message = FOOD_ANALYSIS_TEMPLATE.format(
        meal_type="еда",
        analysis=analysis.get('description', ''),
        advice=analysis.get('advice', ''),
        calories=analysis.get('calories', 0),
        disclaimer=DISCLAIMER_FOOD,
    )
    
    await update.message.reply_text(message)


def parse_food_response(response_text):
    """Парсит ответ Gemini в словарь"""
    lines = response_text.split('\n')
    result = {}
    
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
