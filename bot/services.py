import os
import asyncio
import json
import io
import urllib.parse
import logging
from io import BytesIO

import aiohttp
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot, types
from aiogram.types import BufferedInputFile

from bot.config import (
    PROTALK_BOT_ID,
    PROTALK_TOKEN,
    PROTALK_FUNCTION_ID,
    STYLE_PROMPT_MAP,
    FONTS_FILES,
    OCCASION_TEXT_MAP,
)
from bot.database import (
    increment_generations,
    get_credits,
    add_credits,
    set_user_state,
    save_postcard,
)

logger = logging.getLogger(__name__)

# Prefix used in handlers.py when user enters a custom occasion
CUSTOM_OCCASION_PREFIX = "✏️ "

# Module-level constant — avoids recreating dict on every format_image_text call
_OCCASION_DISPLAY_MAP: dict[str, str] = {
    "день рождения": "с Днём Рождения",
    "свадьбу": "с Днём Свадьбы",
    "рождение ребёнка": "с Новорожденным",
    "8 марта": "с 8 Марта",
    "завершение учёбы": "с Выпуском",
}


async def fetch_with_retry(
    url: str,
    session: aiohttp.ClientSession,
    retries: int = 3,
    delay: int = 2,
) -> aiohttp.ClientResponse:
    """Make HTTP GET with automatic retries on failure."""
    for attempt in range(retries):
        try:
            resp = await session.get(url)
            if resp.status == 200:
                return resp
            logger.warning(f"Attempt {attempt + 1}: status {resp.status} for {url}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}: exception: {e}")

        if attempt < retries - 1:
            await asyncio.sleep(delay)

    raise Exception(f"Failed to fetch after {retries} attempts: {url}")


async def get_greeting_text_from_protalk(
    name: str, occasion: str, fallback: str = "Поздравляю!"
) -> str:
    """Fetch AI-generated greeting caption from ProTalk API."""
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
                    # FIX: use `result` (clean Python str), not `raw` (JSON with quotes)
                    or (result if isinstance(result, str) else "")
                )
            except json.JSONDecodeError:
                text = raw

            return (text or "").strip() or fallback

    except Exception as e:
        logger.error(f"get_greeting_text_from_protalk failed: {e}", exc_info=True)
        return fallback


def format_image_text(name: str, occasion: str, is_custom: bool) -> str:
    """Return greeting text for the image based on name, occasion and mode."""
    if is_custom:
        return f"{name}, поздравляю!"

    # Direct match on mapped occasion value (e.g. "день рождения")
    display = _OCCASION_DISPLAY_MAP.get(occasion.lower())
    if display:
        return f"{name}, {display}!"

    # Fallback: try matching full emoji key from OCCASION_TEXT_MAP
    for emoji_key, val in OCCASION_TEXT_MAP.items():
        if emoji_key == occasion or val == occasion:
            d = _OCCASION_DISPLAY_MAP.get(val)
            if d:
                return f"{name}, {d}!"

    return f"{name}, поздравляю!"


def wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw
) -> str:
    """Wrap text lines to fit within max_width pixels."""
    lines = []
    for block in text.split("\n"):
        words = block.split()
        if not words:
            lines.append("")
            continue
        current_line = words[0]
        for word in words[1:]:
            test_line = current_line + " " + word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        lines.append(current_line)
    return "\n".join(lines)


def apply_text_to_image(img_bytes: bytes, text: str, font_name: str) -> bytes:
    """Draw centred text with semi-transparent drop-shadow; return JPEG bytes."""
    # Convert to RGBA for alpha-compositing (shadow transparency)
    image = Image.open(BytesIO(img_bytes)).convert("RGBA")
    width, height = image.size

    # Draw on a transparent overlay so shadow is truly semi-transparent
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        FONTS_FILES.get(font_name, FONTS_FILES["Comfortaa"]),
    )
    font_size = max(24, height // 10)
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        logger.warning(f"Font not found: {font_path}, using default")
        font = ImageFont.load_default()

    wrapped = wrap_text(text, font, int(width * 0.8), draw)
    bbox = draw.textbbox((0, 0), wrapped, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = (height - text_h) // 2

    shadow = max(2, font_size // 20)
    # FIX: draw on RGBA overlay — alpha value (160) now works correctly
    draw.text((x + shadow, y + shadow), wrapped, font=font, fill=(0, 0, 0, 160))
    draw.text((x, y), wrapped, font=font, fill=(255, 255, 255, 255))

    # Composite overlay onto original, convert back to RGB for JPEG
    result_image = Image.alpha_composite(image, overlay).convert("RGB")

    output = BytesIO()
    result_image.save(output, format="JPEG", quality=92)
    return output.getvalue()


async def generate_postcard(
    chat_id: int, message: types.Message, payload: dict, bot: Bot
):
    """Generate postcard image via ProTalk, overlay text and send to user."""
    occasion = payload["occasion"]
    style = payload["style"]
    font_name = payload.get("font", "Comfortaa")
    text_mode = payload.get("text_mode", "ai")
    text_input = payload["text_input"]
    addressee = payload.get("addressee", text_input)

    # Define early to avoid NameError inside except block
    caption_for_db = text_input.strip()

    wait_msg = await message.answer(
        "⏳ Рисую открытку, это может занять до минуты. Подождите..."
    )

    try:
        # FIX: use CUSTOM_OCCASION_PREFIX constant instead of unicode escape
        is_custom = occasion.startswith(CUSTOM_OCCASION_PREFIX)
        occasion_text = (
            occasion[len(CUSTOM_OCCASION_PREFIX):].strip()
            if is_custom
            else next(
                (v for k, v in OCCASION_TEXT_MAP.items() if k in occasion), "праздник"
            )
        )

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

        async with aiohttp.ClientSession() as session:

            async def fetch_image() -> bytes:
                resp = await fetch_with_retry(image_url, session, retries=3, delay=5)
                return await resp.read()

            if text_mode == "ai":
                image_bytes, greeting_caption = await asyncio.gather(
                    fetch_image(),
                    get_greeting_text_from_protalk(addressee, occasion_text),
                )
                caption_for_db = greeting_caption
            else:
                image_bytes = await fetch_image()
                caption_for_db = text_input.strip()

        text_to_draw = format_image_text(addressee, occasion_text, is_custom)
        final_img_bytes = apply_text_to_image(image_bytes, text_to_draw, font_name)

        pm_caption = (
            f"..., {caption_for_db}\n\n"
            f"\U0001f4a1 <b>Открытка готова!</b>\n"
            f"Чтобы отправить её с именем, напишите в любом чате:\n"
            f"<code>@pozdravish_bot Имя</code>"
        )

        msg = await message.answer_photo(
            photo=BufferedInputFile(final_img_bytes, filename="postcard.jpg"),
            caption=pm_caption,
            parse_mode="HTML",
        )

        if msg and msg.photo:
            save_postcard(chat_id, msg.photo[-1].file_id, caption_for_db)

        increment_generations()
        add_credits(chat_id, -1)

        credits = get_credits(chat_id)
        await message.answer(
            f"Осталось бесплатных открыток: <b>{credits}</b>", parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"generate_postcard error: {e}", exc_info=True)
        await message.answer(
            f"\U0001f614 Произошла ошибка при связи с нейросетью. Серверы сейчас перегружены.\n"
            f"<b>Код ошибки:</b> {str(e)[:100]}\n"
            f"Ваш кредит <b>не списан</b>. Попробуйте ещё раз через пару минут.",
            parse_mode="HTML",
        )
        set_user_state(
            chat_id,
            {"occasion": None, "style": None, "font": None, "text_mode": None},
        )

    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass
