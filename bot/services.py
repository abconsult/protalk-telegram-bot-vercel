import os
import aiohttp
import logging
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from aiogram.types import BufferedInputFile
from aiogram import Bot
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from bot.config import (
    PROTALK_BOT_ID,
    PROTALK_TOKEN,
    PROTALK_FUNCTION_ID,
    STYLE_PROMPT_MAP,
    FONTS_FILES,
    OCCASION_TEXT_MAP,
)
from bot.database import increment_generations, get_credits, add_credits

logger = logging.getLogger(__name__)

async def fetch_with_retry(url: str, session: aiohttp.ClientSession, retries: int = 3, delay: int = 2) -> aiohttp.ClientResponse:
    """Wrapper to make HTTP requests with automatic retries on failure."""
    for attempt in range(retries):
        try:
            resp = await session.get(url)
            if resp.status == 200:
                return resp
            logger.warning(f"Attempt {attempt + 1}: Received status {resp.status} for {url}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}: Exception connecting to API: {e}")
            
        if attempt < retries - 1:
            await asyncio.sleep(delay)
            
    raise Exception(f"Failed to fetch data after {retries} attempts.")


async def get_greeting_text_from_protalk(name: str, occasion: str) -> str:
    meta_prompt = (
        f"Напиши короткое красивое поздравление на русском языке. "
        f"Получатель: {name}. Повод: {occasion}. "
        f"Стиль: тёплый, искренний, 2-3 предложения максимум. "
        f"Ответь ТОЛЬКО текстом поздравления, без кавычек и пояснений."
    )

    protalk_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={urllib.parse.quote(meta_prompt)}"
        f"&output=text"
    )
    
    text = await call_llm_api(system_prompt, user_prompt)
    if text:
        text = text[0].lower() + text[1:]
    return text

def format_image_text(occasion: str) -> str:
    """Return short universal text to put on the image based on occasion."""
    mapping = {
        "🎂 День рождения": "С Днём\nРождения!",
        "💍 Свадьба": "С Днём\nСвадьбы!",
        "👶 Рождение ребёнка": "С Новорожденным!",
        "🌸 8 марта": "С 8 Марта!",
        "🎓 Завершение учёбы": "С Выпуском!",
    }
    if occasion in mapping:
        return mapping[occasion]
        
    clean = occasion.replace("✏️", "").strip()
    words = clean.split()[:3]
    return "\n".join(words).title()

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw) -> str:
    """Wrap text to fit within max_width."""
    lines = []
    for block in text.split('\n'):
        words = block.split()
        if not words:
            lines.append("")
            continue
            
        current_line = words[0]
        for word in words[1:]:
            test_line = current_line + " " + word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            width = bbox[2] - bbox[0]
            if width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        lines.append(current_line)
    return "\n".join(lines)

def apply_text_to_image(img_bytes: bytes, text: str, font_name: str) -> bytes:
    """Draw text onto the center of the image."""
    image = Image.open(BytesIO(img_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    
    font_path = os.path.join(os.path.dirname(__file__), "..", FONTS_FILES.get(font_name, FONTS_FILES["Comfortaa"]))
    
    try:
        async with aiohttp.ClientSession() as session:
            resp = await fetch_with_retry(protalk_url, session, retries=3)
            raw = await resp.text()
            
            try:
                result = json.loads(raw)
                text = (
                    (result.get("result") if isinstance(result, dict) else None)
                    or (result.get("text") if isinstance(result, dict) else None)
                    or (result.get("response") if isinstance(result, dict) else None)
                    or (raw if isinstance(result, str) else "")
                )
            except json.JSONDecodeError:
                text = raw

            text = (text or "").strip()
            return text or fallback
    except Exception as e:
        logger.error(f"Error fetching greeting text (all retries failed): {e}", exc_info=True)
        return fallback


async def generate_postcard(chat_id: int, message: types.Message, payload: dict):
    occasion = payload["occasion"]
    style = payload["style"]
    text_mode = payload.get("text_mode", "ai")
    text_input = payload["text_input"]

    wait_msg = await message.answer("⏳ Рисую открытку, это может занять до минуты. Подождите...")

    is_custom = occasion.startswith("✏️ ")
    if is_custom:
        occasion_text = occasion.replace("✏️ ", "").strip()
    else:
        occasion_text = next((v for k, v in OCCASION_TEXT_MAP.items() if k in occasion), "праздник")

    prompt_template = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["Минимализм"])
    image_prompt = prompt_template.format(occasion=occasion_text)

    image_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={urllib.parse.quote(image_prompt)}"
        f"&output=image"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async def fetch_image():
                resp = await fetch_with_retry(image_url, session, retries=3, delay=5)
                return await resp.read()

            if text_mode == "ai":
                image_bytes, greeting_caption = await asyncio.gather(
                    fetch_image(),
                    get_greeting_text_from_protalk(text_input, occasion_text),
                )
            else:
                image_bytes = await fetch_image()
                greeting_caption = "Ваша открытка готова! ✨"

        img = Image.open(io.BytesIO(image_bytes))
        draw = ImageDraw.Draw(img)

        if text_mode == "ai":
            if occasion_text == "день рождения":
                text_to_draw = f"С Днём Рождения,\n{text_input}!"
            elif occasion_text == "свадьбу":
                text_to_draw = f"{text_input},\nс днём свадьбы!"
            elif occasion_text == "рождение ребёнка":
                text_to_draw = f"{text_input},\nс новорожденным!"
            elif occasion_text == "8 марта":
                text_to_draw = f"{text_input},\nс 8 Марта!"
            elif occasion_text == "завершение учёбы":
                text_to_draw = f"{text_input},\nс завершением учёбы!"
            else:
                text_to_draw = f"{text_input},\nпоздравляю!"
        else:
            caption_for_db = payload.get("text_input", "").strip()
            
        pm_caption = (
            f"..., {caption_for_db}\n\n"
            f"💡 <b>Открытка готова!</b>\n"
            f"Чтобы отправить её с именем, напишите в любом чате:\n"
            f"<code>@pozdravish_bot Имя</code>"
        )
        
        # Send result
        msg = await message.answer_photo(
            photo=BufferedInputFile(final_img_bytes, filename="postcard.jpg"),
            caption=pm_caption,
            parse_mode="HTML"
        )
        
        # Save to DB for inline mode
        from bot.database import save_postcard
        if msg and msg.photo:
            file_id = msg.photo[-1].file_id
            save_postcard(chat_id, file_id, caption_for_db)
        
        # Increment stats & deduct credits
        increment_generations()
        add_credits(chat_id, -1)
        
        # Cleanup status message
        try:
            await status_msg.delete()
        except Exception:
            pass
            
        credits = get_credits(chat_id)
        await message.answer(f"Осталось бесплатных открыток: <b>{credits}</b>", parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Generation error: {e}", exc_info=True)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"😔 Произошла ошибка при связи с нейросетью. Серверы сейчас перегружены.\n"
            f"<b>Код ошибки:</b> {str(e)[:100]}\n"
            f"Ваш кредит <b>не списан</b>. Пожалуйста, попробуйте сгенерировать открытку ещё раз через пару минут.",
            parse_mode="HTML"
        )
        set_user_state(chat_id, {"occasion": None, "style": None, "font": None, "text_mode": None})

    except Exception as e:
        logger.error(f"Error in generate_postcard: {e}", exc_info=True)
        await message.answer("❌ Сервер генерации временно не отвечает. Пожалуйста, попробуйте чуть позже.")
    finally:
        await wait_msg.delete()
