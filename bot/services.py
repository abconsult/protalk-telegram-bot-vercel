import os
import asyncio
import json
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

CUSTOM_OCCASION_PREFIX = "✏️ "

_OCCASION_DISPLAY_MAP: dict[str, str] = {
    "день рождения": "с Днём Рождения",
    "свадьбу": "с Днём Свадьбы",
    "рождение ребёнка": "с Новорожденным",
    "8 марта": "с 8 Марта",
    "завершение учёбы": "с Выпуском",
}

# Local caption fallback used when ProTalk text API times out
_OCCASION_CAPTION_FALLBACK: dict[str, str] = {
    "день рождения": "желаю счастья, здоровья и всего самого лучшего!",
    "свадьбу": "желаю любви, гармонии и семейного счастья!",
    "рождение ребёнка": "пусть малыш радует и растёт здоровым и любимым!",
    "8 марта": "желаю радости, тепла и весны в душе!",
    "завершение учёбы": "желаю яркого будущего и больших успехов!",
}


async def fetch_with_retry(
    url: str,
    session: aiohttp.ClientSession,
    retries: int = 3,
    delay: int = 2,
) -> aiohttp.ClientResponse:
    for attempt in range(retries):
        try:
            resp = await session.get(url)
            if resp.status == 200:
                return resp
            logger.warning(f"Attempt {attempt + 1}: status {resp.status}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}: exception: {e}")
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    raise Exception(f"Failed to fetch after {retries} attempts: {url}")


async def get_greeting_text_from_protalk(
    addressee: str,
    occasion: str,
    context: str | None = None,
    fallback: str = "Поздравляю!",
) -> str:
    base_prompt = (
        "Напиши короткое красивое поздравление на русском языке. "
        f"Получатель: {addressee}. "
        f"Повод: {occasion}. "
    )
    if context:
        base_prompt += f"Дополнительные пожелания: {context}. "
    base_prompt += (
        "Стиль: тёплый, искренний, 2-3 предложения максимум. "
        "Ответь ТОЛЬКО текстом поздравления, без кавычек и пояснений."
    )

    protalk_url = (
        "https://api.pro-talk.ru/api/v1.0/run_function_get"
        f"?function_id={PROTALK_FUNCTION_ID}"
        f"&bot_id={PROTALK_BOT_ID}"
        f"&bot_token={PROTALK_TOKEN}"
        f"&prompt={urllib.parse.quote(base_prompt)}"
        f"&output=text"
    )

    logger.info(f"PROTALK TEXT: calling for '{addressee}' / '{occasion}'")
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            resp = await fetch_with_retry(protalk_url, session, retries=1, delay=0)
            raw = await resp.text()

        logger.info(f"PROTALK TEXT: raw='{raw[:200]}'")

        try:
            result = json.loads(raw)
            text = (
                (result.get("result") if isinstance(result, dict) else None)
                or (result.get("text") if isinstance(result, dict) else None)
                or (result.get("response") if isinstance(result, dict) else None)
                or (result if isinstance(result, str) else "")
            )
        except json.JSONDecodeError:
            text = raw

        final = (text or "").strip() or fallback
        logger.info(f"PROTALK TEXT: result='{final[:80]}'")
        return final

    except Exception as e:
        logger.info(f"PROTALK TEXT ERROR: {type(e).__name__}: {e}")
        return fallback


async def safe_greeting(
    addressee: str,
    occasion_text: str,
    context: str | None,
    timeout_secs: float = 8.0,
) -> str:
    """Call ProTalk text API with hard timeout; fall back to local text on timeout."""
    local_fallback = _OCCASION_CAPTION_FALLBACK.get(
        occasion_text.lower(),
        "поздравляю с праздником!",
    )
    try:
        result = await asyncio.wait_for(
            get_greeting_text_from_protalk(
                addressee=addressee,
                occasion=occasion_text,
                context=context,
                fallback=local_fallback,
            ),
            timeout=timeout_secs,
        )
        return result
    except asyncio.TimeoutError:
        logger.info(f"PROTALK TEXT: timeout {timeout_secs}s — using local fallback")
        return local_fallback


def format_image_text(name: str, occasion: str = "", is_custom: bool = False) -> str:
    """Text drawn on the postcard image."""
    if not is_custom:
        display = _OCCASION_DISPLAY_MAP.get(occasion.lower())
        if display:
            return f"{name}, {display}!"
    return f"{name}, поздравляю!"


def wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw
) -> str:
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
    image = Image.open(BytesIO(img_bytes)).convert("RGBA")
    width, height = image.size
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
    draw.text((x + shadow, y + shadow), wrapped, font=font, fill=(0, 0, 0, 160))
    draw.text((x, y), wrapped, font=font, fill=(255, 255, 255, 255))

    result_image = Image.alpha_composite(image, overlay).convert("RGB")
    output = BytesIO()
    result_image.save(output, format="JPEG", quality=92)
    return output.getvalue()


async def generate_postcard(
    chat_id: int, message: types.Message, payload: dict, bot: Bot
):
    occasion = payload["occasion"]
    style = payload["style"]
    font_name = payload.get("font", "Comfortaa")
    text_mode = payload.get("text_mode", "ai")
    text_input = payload["text_input"]  # ai_context or custom text
    addressee = payload.get("addressee", text_input)

    caption_for_db = text_input.strip()

    wait_msg = await message.answer(
        "⏳ Рисую открытку, это может занять до минуты. Подождите..."
    )

    try:
        is_custom = occasion.startswith(CUSTOM_OCCASION_PREFIX)
        occasion_text = (
            occasion[len(CUSTOM_OCCASION_PREFIX):].strip()
            if is_custom
            else next(
                (v for k, v in OCCASION_TEXT_MAP.items() if k in occasion), "праздник"
            )
        )

        logger.info(f"POSTCARD: mode={text_mode} occasion='{occasion_text}' addressee='{addressee}'")

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

        timeout_img = aiohttp.ClientTimeout(total=25)

        async def fetch_image() -> bytes:
            async with aiohttp.ClientSession(timeout=timeout_img) as session:
                resp = await fetch_with_retry(image_url, session, retries=3, delay=3)
                return await resp.read()

        if text_mode == "ai":
            # Parallel: image + AI caption, caption capped at 8s
            image_bytes, caption_for_db = await asyncio.gather(
                fetch_image(),
                safe_greeting(
                    addressee=addressee,
                    occasion_text=occasion_text,
                    context=text_input,
                    timeout_secs=8.0,
                ),
            )
            logger.info(f"POSTCARD: caption='{caption_for_db[:80]}'")
        else:
            image_bytes = await fetch_image()
            caption_for_db = text_input.strip()

        text_to_draw = format_image_text(addressee, occasion_text, is_custom)
        logger.info(f"POSTCARD: text_to_draw='{text_to_draw}'")
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
            {"occasion": None, "style": None, "font": None, "text_mode": None,
             "ai_context": None, "addressee": None},
        )

    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass
