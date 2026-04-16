from datetime import datetime, timedelta
import pytz

MSK = pytz.timezone('Europe/Moscow')


def now_msk():
    """Текущее время в Москве"""
    return datetime.now(MSK)


def time_to_utc(hhmm: str):
    """Переводит время МСК (HH:MM) в UTC для планировщика"""
    now = now_msk()
    hour, minute = map(int, hhmm.split(':'))
    msk_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc_time = msk_time.astimezone(pytz.UTC)
    return utc_time.strftime('%H:%M')


def calculate_calorie_norm(weight, height, age):
    """Расчёт нормы калорий по формуле Миффлина-Сан Жеора (для женщин)"""
    bmr = (10 * weight) + (6.25 * height) - (5 * age) - 161
    return int(bmr * 1.2)


def calculate_bio_age(face_analysis, water_score, food_score):
    """Расчёт биологического возраста"""
    base_age = 50
    skin_score = face_analysis.get('skin_quality', 5)
    age_delta = (water_score + food_score + skin_score - 15) * 0.5
    return max(30, min(80, base_age - age_delta))


def validate_time(time_str):
    """Проверка формата времени"""
    try:
        hour, minute = map(int, time_str.split(':'))
        return 0 <= hour < 24 and 0 <= minute < 60
    except:
        return False


def get_water_glasses(tg_id):
    """Сколько стаканов воды выпил сегодня"""
    from database import get_today_water
    _, total_ml = get_today_water(tg_id)
    return total_ml // 250


def get_food_status(tg_id):
    """Получить статус питания за день"""
    from database import get_today_food, get_user
    user = get_user(tg_id)
    entries, total_cal = get_today_food(tg_id)
    norm = calculate_calorie_norm(user.weight, user.height, user.age)
    return total_cal, norm


def generate_partner_link(product_type):
    """Генерирует партнёрскую ссылку"""
    from config import PARTNER_LINKS
    return PARTNER_LINKS.get(product_type, "https://www.wildberries.ru")
