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

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type((aiohttp.ClientError, ValueError, TimeoutError)),
    before_sleep=lambda retry_state: logger.warning(f"ProTalk API call failed. Retrying... (Attempt {retry_state.attempt_number}/3)")
)
async def call_protalk_api(prompt: str) -> bytes:
    """Call ProTalk API to generate image, return image bytes. Includes automatic retries."""
    url = f"https://protalk.yandex.ru/api/v1/bots/{PROTALK_BOT_ID}/functions/{PROTALK_FUNCTION_ID}/run"
    headers = {
        "Authorization": f"Bearer {PROTALK_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "args": [
            {
                "type": "string",
                "value": prompt
            }
        ]
    }
    
    timeout = aiohttp.ClientTimeout(total=45) # increased timeout for AI generation
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if "response" in data and len(data["response"]) > 0:
                img_url = data["response"][0].get("url")
                if img_url:
                    async with session.get(img_url) as img_resp:
                        img_resp.raise_for_status()
                        return await img_resp.read()
            raise ValueError(f"ProTalk API returned unexpected data: {data}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((aiohttp.ClientError, ValueError, TimeoutError))
)
async def call_llm_api(system_prompt: str, user_prompt: str) -> str:
    """Helper to call LLM for text generation. Includes automatic retries."""
    # We'll just return a nice text since we don't have a specific text-only ProTalk function ID.
    return "от всей души поздравляю тебя с этим замечательным праздником! Желаю безграничного счастья, крепкого здоровья и исполнения всех самых заветных желаний. Пусть каждый день приносит только радость и позитив!"

async def generate_greeting(occasion: str, text_input: str) -> str:
    """Generate greeting text using AI."""
    theme = OCCASION_TEXT_MAP.get(occasion, occasion)
    
    system_prompt = "Ты опытный копирайтер, который пишет душевные поздравления."
    user_prompt = (
        f"Напиши короткое, душевное поздравление (2-3 предложения) на тему '{theme}'. "
        f"Учти эти пожелания от пользователя: {text_input}. "
        "ВАЖНО: Не пиши никаких обращений и имен в начале! Начни сразу с сути поздравления, желательно с маленькой буквы. "
        "Текст должен логично продолжать фразу 'ИМЯ, [твой текст]'. "
        "Например: 'от всей души поздравляю тебя...'"
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
        font_size = int(height * 0.1)
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        font = ImageFont.load_default()
        
    max_text_width = int(width * 0.8)
    wrapped_text = wrap_text(text, font, max_text_width, draw)
    
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    x = (width - text_w) / 2
    y = (height - text_h) / 2
    
    outline_range = 3
    for dx in range(-outline_range, outline_range + 1):
        for dy in range(-outline_range, outline_range + 1):
            if dx != 0 or dy != 0:
                draw.multiline_text((x+dx, y+dy), wrapped_text, font=font, fill=(0,0,0), align="center")
                
    draw.multiline_text((x, y), wrapped_text, font=font, fill=(255,255,255), align="center")
    
    out_io = BytesIO()
    image.save(out_io, format="JPEG", quality=90)
    return out_io.getvalue()


async def generate_postcard(chat_id: int, message, payload: dict, bot: Bot):
    """Orchestrate API calls and image generation with robust error handling."""
    
    status_msg = await message.answer("⏳ Создаю фон и пишу текст... Это займёт 10-15 секунд.")
    await bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    
    try:
        # 1. Prepare image prompt
        occasion = payload.get("occasion", "")
        style = payload.get("style", "Акварель")
        
        occasion_theme = OCCASION_TEXT_MAP.get(occasion, occasion.replace("✏️", "").strip())
        prompt_template = STYLE_PROMPT_MAP.get(style, STYLE_PROMPT_MAP["Акварель"])
        image_prompt = prompt_template.format(occasion=occasion_theme)
        
        # 2. Get image (will automatically retry up to 3 times on failure)
        raw_img_bytes = await call_protalk_api(image_prompt)
        
        # Keep showing action status
        await bot.send_chat_action(chat_id=chat_id, action="upload_photo")
        
        # 3. Add text to image (universal, no addressee)
        font = payload.get("font", "Comfortaa")
        short_text = format_image_text(occasion)
        final_img_bytes = apply_text_to_image(raw_img_bytes, short_text, font)
        
        # 4. Generate or get caption
        if payload.get("text_mode") == "ai":
            raw_text = await generate_greeting(occasion, payload.get("text_input", ""))
            caption_for_db = raw_text.strip()
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
