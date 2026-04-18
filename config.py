import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///madonna.db")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

GEMINI_MODEL = "gemini-1.5-flash-latest"
SUB_PRICE = 1490

WATER_TIMES = ["05:30", "07:00", "08:30", "10:00", "11:30", "13:00", "14:30", "16:00", "17:30"]
FOOD_TIMES = ["12:00", "14:00", "17:00", "19:30"]
SLEEP_TIME = "20:30"
WAKE_TIME = "07:00"

PARTNER_LINKS = {
    "collagen": "https://www.wildberries.ru/catalog/12345678/detail.aspx",
    "face_massager": "https://www.wildberries.ru/catalog/87654321/detail.aspx",
}
