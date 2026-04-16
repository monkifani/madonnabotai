from telegram import Update
from telegram.ext import ContextTypes
from database import add_face_scan, get_user, get_last_face_scan, update_user
from utils.prompts import FACE_ANALYZER_PROMPT
from utils.text_messages import FACE_ANALYSIS_TEMPLATE
from utils.disclaimers import DISCLAIMER_FACE
from utils.helpers import calculate_bio_age
from config import GOOGLE_API_KEY, GEMINI_MODEL
import google.generativeai as genai

genai.configure(api_key=GOOGLE_API_KEY)


async def handle_face_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь прислал селфи"""
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь — /start")
        return
    
    photo = update.message.photo[-1]
    await analyze_face(update, context, photo)


async def analyze_face(update: Update, context: ContextTypes.DEFAULT_TYPE, photo=None):
    """Анализ лица"""
    if photo is None:
        photo = update.message.photo[-1]
    
    user = get_user(update.effective_user.id)
    photo_file = await photo.get_file()
    
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
        await photo_file.download_to_drive(tmp.name)
        
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = FACE_ANALYZER_PROMPT
        
        from PIL import Image
        image = Image.open(tmp.name)
        response = model.generate_content([prompt, image])
        
    analysis = parse_face_response(response.text)
    
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
    
    message = FACE_ANALYSIS_TEMPLATE.format(
        analysis=analysis.get('summary', ''),
        bio_age=analysis.get('bio_age', user.age),
        previous_comparison=comparison,
        recommendation=analysis.get('recommendation', ''),
        disclaimer=DISCLAIMER_FACE,
    )
    
    await update.message.reply_text(message)


def parse_face_response(response_text):
    """Парсит ответ Gemini в словарь"""
    lines = response_text.split('\n')
    result = {}
    
    for line in lines:
        if line.startswith('ТУРГОР:'):
            result['turgor'] = line.replace('ТУРГОР:', '').strip()
        elif line.startswith('МОРЩИНЫ:'):
            result['wrinkles'] = line.replace('МОРЩИНЫ:', '').strip()
        elif line.startswith('ПИГМЕНТАЦИЯ:'):
            result['pigmentation'] = line.replace('ПИГМЕНТАЦИЯ:', '').strip()
        elif line.startswith('ПОРЫ:'):
            result['pores'] = line.replace('ПОРЫ:', '').strip()
        elif line.startswith('ВОЗРАСТ:'):
            try:
                result['bio_age'] = float(line.replace('ВОЗРАСТ:', '').strip())
            except:
                result['bio_age'] = 50
        elif line.startswith('РЕКОМЕНДАЦИЯ:'):
            result['recommendation'] = line.replace('РЕКОМЕНДАЦИЯ:', '').strip()
        elif line.startswith('ОПИСАНИЕ:'):
            result['summary'] = line.replace('ОПИСАНИЕ:', '').strip()
    
    return result
