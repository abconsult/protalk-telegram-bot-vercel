import sys
import os
# Добавляем корневую папку проекта в sys.path, чтобы Vercel мог найти модуль bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from fastapi import FastAPI, Request, HTTPException, Header
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from bot.config import TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET
from bot.handlers import register_handlers

# Настраиваем логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Инициализируем бота и диспетчер
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp  = Dispatcher()

# Регистрируем все обработчики сообщений
register_handlers(dp, bot)

@app.post("/api/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    # Если секрет задан в настройках, проверяем его наличие в заголовке от Telegram
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        logger.warning("Unauthorized webhook access attempt")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        update_dict = await request.json()
        update = Update(**update_dict)
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
        # We still return 200 OK to Telegram so it doesn't infinitely retry broken updates
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Pozdravish Bot is running and secure"}
