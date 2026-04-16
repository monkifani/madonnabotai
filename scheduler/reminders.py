from telegram.ext import ContextTypes, JobQueue
from database import get_all_active_users, get_user, add_water, add_reminder, get_today_water
from utils.text_messages import WATER_REMINDERS, FOOD_REMINDERS
from utils.helpers import now_msk, time_to_utc
from config import WATER_TIMES, FOOD_TIMES
import logging
from datetime import time

logger = logging.getLogger(__name__)


def schedule_water_reminders(job_queue: JobQueue):
    """
    Планирует все напоминания о воде на день.
    Вызывается один раз при старте бота.
    """
    logger.info("Scheduling water reminders...")
    
    for i, water_time_msk in enumerate(WATER_TIMES):
        # Конвертируем время МСК в UTC для APScheduler
        utc_time = time_to_utc(water_time_msk)
        hour, minute = map(int, utc_time.split(':'))
        
        job_queue.run_daily(
            callback=send_water_reminder,
            time=time(hour=hour, minute=minute),
            name=f"water_{i}",
            data={'glass_number': i}  # Передаем номер стакана
        )
        logger.info(f"Scheduled water reminder {i} at {water_time_msk} MSK ({utc_time} UTC)")


def schedule_food_reminders(job_queue: JobQueue):
    """
    Планирует напоминания о приёме пищи.
    """
    logger.info("Scheduling food reminders...")
    
    for meal_time_msk in FOOD_TIMES:
        utc_time = time_to_utc(meal_time_msk)
        hour, minute = map(int, utc_time.split(':'))
        
        job_queue.run_daily(
            callback=send_food_reminder,
            time=time(hour=hour, minute=minute),
            name=f"food_{meal_time_msk}"
        )
        logger.info(f"Scheduled food reminder at {meal_time_msk} MSK ({utc_time} UTC)")


async def send_water_reminder(context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет напоминание о воде всем активным пользователям.
    Вызывается автоматически по расписанию.
    """
    job = context.job
    glass_number = job.data.get('glass_number', 0) if job.data else 0
    
    logger.info(f"Running water reminder job #{glass_number}")
    
    users = get_all_active_users()
    if not users:
        logger.warning("No active users found for water reminder")
        return
    
    for user in users:
        try:
            # Персонализируем сообщение
            base_message = WATER_REMINDERS[glass_number] if glass_number < len(WATER_REMINDERS) else "Время выпить водички! 💧"
            personalized = base_message.replace("Вы", user.name).replace("Доброе утро", f"Доброе утро, {user.name}")
            
            await context.bot.send_message(
                chat_id=user.tg_id,
                text=personalized
            )
            
            # Логируем отправку
            add_reminder(user.tg_id, f'water_{glass_number}', personalized)
            logger.info(f"Sent water reminder to user {user.tg_id}")
            
        except Exception as e:
            logger.error(f"Failed to send water reminder to user {user.tg_id}: {e}")


async def send_food_reminder(context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет напоминание о еде.
    Определяет тип приёма пищи по времени.
    """
    current_hour = now_msk().hour
    logger.info(f"Running food reminder job at {current_hour}:00 MSK")
    
    # Определяем тип напоминания
    if 11 <= current_hour < 15:
        reminder_type = 'lunch'
    elif 15 <= current_hour < 17:
        reminder_type = 'snack'
    elif 17 <= current_hour < 20:
        reminder_type = 'dinner'
    else:
        reminder_type = 'lunch'  # По умолчанию
    
    users = get_all_active_users()
    
    for user in users:
        try:
            message = FOOD_REMINDERS[reminder_type].replace("Людмила", user.name)
            
            await context.bot.send_message(
                chat_id=user.tg_id,
                text=message
            )
            
            add_reminder(user.tg_id, f'food_{reminder_type}', message)
            logger.info(f"Sent food reminder ({reminder_type}) to user {user.tg_id}")
            
        except Exception as e:
            logger.error(f"Failed to send food reminder to user {user.tg_id}: {e}")


async def send_sleep_reminder(context: ContextTypes.DEFAULT_TYPE):
    """
    Напоминание о подготовке ко сну (за 30 минут до времени сна пользователя).
    """
    logger.info("Running sleep reminder job")
    
    users = get_all_active_users()
    
    for user in users:
        if not user.sleep_time:
            continue
            
        try:
            message = (
                f"🌙 {user.name}, скоро пора спать ({user.sleep_time}).\n"
                f"Выпей стакан воды и сделай лёгкий массаж лица — "
                f"так кожа лучше восстановится за ночь!"
            )
            
            await context.bot.send_message(
                chat_id=user.tg_id,
                text=message
            )
            
            add_reminder(user.tg_id, 'sleep', message)
            logger.info(f"Sent sleep reminder to user {user.tg_id}")
            
        except Exception as e:
            logger.error(f"Failed to send sleep reminder to user {user.tg_id}: {e}")
