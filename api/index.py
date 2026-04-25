import sys
import os
# Добавляем корневую папку проекта в sys.path, чтобы Vercel мог найти модуль bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import json
from fastapi import FastAPI, Request, HTTPException, Header
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from bot.config import TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET
from bot.handlers import register_handlers

# Настраиваем логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Validate required env vars at startup so misconfigured deploys fail loudly
_REQUIRED_ENV = [
    "TELEGRAM_BOT_TOKEN",
    "WEBHOOK_SECRET",
    "WEBHOOK_URL",
    "KIE_API_KEY",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
]
_missing = [v for v in _REQUIRED_ENV if not os.getenv(v)]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")

# Optional vars — warn if absent but don't crash
if not os.getenv("ADMIN_ID"):
    logger.warning("ADMIN_ID is not set — admin commands (/stats, /broadcast) will be disabled")
if not os.getenv("OPENROUTER_API_KEY"):
    logger.warning("OPENROUTER_API_KEY is not set — AI greeting text will use local fallbacks")

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


@app.post("/api/kie-callback")
async def kie_callback(request: Request):
    """
    Webhook endpoint for Kie.ai image generation callbacks.
    
    Receives POST requests from Kie.ai when image generation completes.
    Expected payload matches Kie.ai callback format:
    {
        "code": 200,
        "data": {
            "taskId": "...",
            "state": "success" | "fail",
            "resultJson": "{\"resultUrls\":[\"https://...\"]}",
            "failMsg": "...",
            ...
        },
        "msg": "..."
    }
    """
    try:
        payload = await request.json()
        logger.info(f"KIE CALLBACK: received payload code={payload.get('code')}")
        
        data = payload.get("data", {})
        task_id = data.get("taskId")
        state = data.get("state")
        
        if not task_id:
            logger.warning("KIE CALLBACK: no taskId in payload")
            return {"status": "error", "message": "Missing taskId"}
        
        # Parse resultJson string to dict
        result_json_str = data.get("resultJson")
        if result_json_str and isinstance(result_json_str, str):
            try:
                result_json = json.loads(result_json_str)
            except json.JSONDecodeError:
                logger.error(f"KIE CALLBACK: failed to parse resultJson: {result_json_str}")
                result_json = {}
        else:
            result_json = result_json_str if isinstance(result_json_str, dict) else {}
        
        fail_msg = data.get("failMsg")
        
        # Process callback asynchronously
        from bot.services import process_kie_callback
        success = await process_kie_callback(
            task_id=task_id,
            state=state,
            result_json=result_json,
            fail_msg=fail_msg,
            bot=bot,
        )
        
        if success:
            return {"status": "ok", "message": "Callback processed successfully"}
        else:
            return {"status": "error", "message": "Failed to process callback"}
            
    except Exception as e:
        logger.error(f"KIE CALLBACK: error processing callback: {e}", exc_info=True)
        # Return 200 OK so Kie.ai doesn't retry
        return {"status": "error", "message": str(e)}


@app.get("/")
def root():
    return {"message": "Pozdravish Bot is running and secure"}
