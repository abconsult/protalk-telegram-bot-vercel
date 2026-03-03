import os
import asyncio
import json
import urllib.parse
import logging
import re
import traceback
from io import BytesIO

import aiohttp
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot, types
from aiogram.types import BufferedInputFile

from bot.config import (
    KIE_API_KEY,
    WEBHOOK_URL,
    PROTALK_BOT_ID,
    PROTALK_TOKEN,
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
    save_pending_image_task,
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

_OCCASION_CAPTION_FALLBACK: dict[str, str] = {
    "день рождения": "желаю счастья, здоровья и всего самого лучшего!",
    "свадьбу": "желаю любви, гармонии и семейного счастья!",
    "рождение ребёнка": "пусть малыш радует и растёт здоровым и любимым!",
    "8 марта": "желаю радости, тепла и весны в душе!",
    "завершение учёбы": "желаю яркого будущего и больших успехов!",
}

_FONT_SIZE_MULTIPLIER: dict[str, float] = {
    "Caveat": 1.22,
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
            logger.warning(f"Attempt {attempt + 1}: {type(e).__name__}: {e}")
            logger.warning(traceback.format_exc())
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    raise Exception(f"Failed to fetch after {retries} attempts")


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

    payload = {
        "bot_id": int(PROTALK_BOT_ID),
        "chat_id": f"postcard_text_{addressee}_{occasion}",
        "message": base_prompt,
    }

    logger.info(f"PROTALK TEXT: calling for '{addressee}' / '{occasion}'")
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"https://api.pro-talk.ru/api/v1.0/ask/{PROTALK_TOKEN}",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"PROTALK TEXT: status {resp.status}")
                    return fallback
                raw = await resp.text()

        logger.info(f"PROTALK TEXT: raw='{raw[:200]}'")

        try:
            result = json.loads(raw)
            text = result.get("done", "").strip()
        except (json.JSONDecodeError, AttributeError):
            text = ""

        final = text or fallback
        logger.info(f"PROTALK TEXT: result='{final[:80]}'")
        return final

    except Exception as e:
        logger.info(f"PROTALK TEXT ERROR: {type(e).__name__}: {e}")
        return fallback


async def safe_greeting(
    addressee: str,
    occasion_text: str,
    context: str | None,
    timeout_secs: float = 5.0,
) -> str:
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


async def create_image_task_async(
    image_prompt: str,
    chat_id: int,
    message_id: int,
    payload: dict,
    caption: str,
) -> str:
    """
    Create async image generation task via Kie.ai z-image API.
    Returns task_id, saves context to DB for callback processing.
    """
    if not WEBHOOK_URL:
        raise Exception("WEBHOOK_URL not configured")
    
    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}",
        "Content-Type": "application/json",
    }
    
    callback_url = f"{WEBHOOK_URL}/api/kie-callback"
    
    request_payload = {
        "model": "z-image",
        "callBackUrl": callback_url,
        "input": {
            "prompt": image_prompt,
            "aspect_ratio": "1:1",
        },
    }

    logger.info(f"KIE IMAGE: creating async task with z-image, callback={callback_url}")
    
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.kie.ai/api/v1/jobs/createTask",
            headers=headers,
            json=request_payload,
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"KIE IMAGE: create task failed {resp.status}: {error_text}")
                raise Exception(f"Kie.ai API returned {resp.status}")
            result = await resp.json()
    
    task_id = result.get("data", {}).get("taskId")
    if not task_id:
        logger.error(f"KIE IMAGE: no taskId in response: {result}")
        raise Exception("No taskId in Kie.ai response")
    
    logger.info(f"KIE IMAGE: task created, taskId={task_id}")
    
    # Save context for callback
    save_pending_image_task(
        task_id=task_id,
        data={
            "chat_id": chat_id,
            "message_id": message_id,
            "payload": payload,
            "caption_for_db": caption,
        },
        ttl=300,  # 5 minutes
    )
    
    return task_id


async def download_image(image_url: str) -> bytes:
    """Download image from URL."""
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        resp = await fetch_with_retry(image_url, session, retries=2, delay=1)
        return await resp.read()


def format_image_text(name: str, occasion: str = "", is_custom: bool = False) -> str:
    if not is_custom:
        display = _OCCASION_DISPLAY_MAP.get(occasion.lower())
        if display:
            display = display.replace(" ", "\u00a0")
            return f"{name}, {display}!"
    return f"{name}, поздравляю!"


def _pick_text_colors(image: Image.Image) -> tuple[tuple, tuple]:
    """Analyse centre 40% of image; return (text_color, stroke_color)."""
    w, h = image.size
    margin = 0.3
    crop = image.crop((
        int(w * margin), int(h * margin),
        int(w * (1 - margin)), int(h * (1 - margin)),
    ))
    r, g, b = crop.resize((1, 1), Image.LANCZOS).convert("RGB").getpixel((0, 0))
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    logger.info(f"IMAGE LUMINANCE: {luminance:.1f} (r={r} g={g} b={b})")
    if luminance > 140:
        return (30, 30, 30), (255, 255, 255)
    else:
        return (255, 255, 255), (30, 30, 30)


def wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.Draw
) -> str:
    lines = []
    for block in text.split("\n"):
        # Split only by regular spaces so non-breaking spaces stay in one token.
        words = [word for word in block.split(" ") if word]
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


def _mojibake_score(text: str) -> int:
    # Typical mojibake chunks for UTF-8 decoded as cp1251.
    return len(re.findall(r"[РС][\u0400-\u04FF]", text)) + text.count("�")


def _normalize_cyrillic_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return ""

    # Fast path: already readable enough, skip risky recoding.
    if _mojibake_score(cleaned) == 0:
        return cleaned

    for codec in ("cp1251", "koi8_r"):
        try:
            fixed = cleaned.encode(codec).decode("utf-8")
        except UnicodeError:
            continue
        if fixed and _mojibake_score(fixed) < _mojibake_score(cleaned):
            return fixed
    return cleaned


def _load_font(font_path: str, fallback_path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        logger.warning(f"Font not found or broken: {font_path}, fallback to {fallback_path}")
        try:
            return ImageFont.truetype(fallback_path, size)
        except Exception:
            logger.warning("Fallback font not found, using Pillow default bitmap font")
            return ImageFont.load_default()


def _fit_font_and_wrap(
    draw: ImageDraw.Draw,
    text: str,
    primary_font_path: str,
    fallback_font_path: str,
    font_name: str,
    width: int,
    height: int,
) -> tuple[ImageFont.FreeTypeFont, str]:
    multiplier = _FONT_SIZE_MULTIPLIER.get(font_name, 1.0)
    start_size = max(36, int(height * 0.16 * multiplier))
    min_size = 28
    max_width = int(width * 0.84)
    max_height = int(height * 0.48)

    for size in range(start_size, min_size - 1, -2):
        font = _load_font(primary_font_path, fallback_path, size)
        wrapped = wrap_text(text, font, max_width, draw)
        bbox = draw.textbbox((0, 0), wrapped, font=font, align="center")
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w <= max_width and text_h <= max_height:
            return font, wrapped

    font = _load_font(primary_font_path, fallback_font_path, min_size)
    return font, wrap_text(text, font, max_width, draw)


def apply_text_to_image(img_bytes: bytes, text: str, font_name: str) -> bytes:
    image = Image.open(BytesIO(img_bytes)).convert("RGBA")
    width, height = image.size

    text_color, stroke_color = _pick_text_colors(image)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    requested_font_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        FONTS_FILES.get(font_name, FONTS_FILES["Comfortaa"]),
    )
    fallback_font_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        FONTS_FILES["Comfortaa"],
    )
    safe_text = _normalize_cyrillic_text(text)
    font, wrapped = _fit_font_and_wrap(
        draw=draw,
        text=safe_text,
        primary_font_path=requested_font_path,
        fallback_font_path=fallback_font_path,
        font_name=font_name,
        width=width,
        height=height,
    )

    bbox = draw.textbbox((0, 0), wrapped, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) / 2
    y = (height - text_h) / 2

    draw.multiline_text(
        (x, y),
        wrapped,
        font=font,
        fill=text_color,
        align="center",
        stroke_width=2,
        stroke_fill=stroke_color,
    )

    result_image = Image.alpha_composite(image, overlay).convert("RGB")
    output = BytesIO()
    result_image.save(output, format="JPEG", quality=92)
    return output.getvalue()


async def _keep_uploading(bot: Bot, chat_id: int, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action="upload_photo")
        except Exception:
            pass
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=4.0)
        except asyncio.TimeoutError:
            pass


def _friendly_error(e: Exception) -> str:
    """Return a short user-friendly error description without internal URLs or paths."""
    msg = str(e)
    # Hide any URL (starts with http)
    if "http" in msg:
        return "Нейросеть не ответила вовремя"
    # Timeout errors
    if "timeout" in msg.lower() or "TimeoutError" in type(e).__name__:
        return "Превышен лимит ожидания"
    # Connection errors
    if "connect" in msg.lower() or "ClientConnector" in type(e).__name__:
        return "Ошибка соединения"
    # Generic fallback — show short message without URLs
    clean = msg.split("\n")[0][:80]
    return clean if clean else "Неизвестная ошибка"


async def generate_postcard(
    chat_id: int, message: types.Message, payload: dict, bot: Bot
):
    """Generate postcard asynchronously using callback workflow."""
    occasion = payload["occasion"]
    style = payload["style"]
    font_name = payload.get("font", "Comfortaa")
    text_mode = payload.get("text_mode", "ai")
    text_input = payload["text_input"]
    addressee = payload.get("addressee", text_input)

    caption_for_db = text_input.strip()

    wait_msg = await message.answer(
        "⏳ Генерирую открытку... Пожалуйста, подождите."
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

        # Generate caption if needed
        if text_mode == "ai":
            caption_for_db = await safe_greeting(
                addressee=addressee,
                occasion_text=occasion_text,
                context=text_input,
                timeout_secs=5.0,
            )
            logger.info(f"POSTCARD: caption='{caption_for_db[:80]}'")
        else:
            caption_for_db = text_input.strip()

        # Create async image generation task
        task_id = await create_image_task_async(
            image_prompt=image_prompt,
            chat_id=chat_id,
            message_id=wait_msg.message_id,
            payload=payload,
            caption=caption_for_db,
        )
        
        logger.info(f"POSTCARD: async task created, taskId={task_id}, waiting for callback")

    except Exception as e:
        logger.error(f"generate_postcard error: {e}", exc_info=True)
        friendly = _friendly_error(e)
        await wait_msg.edit_text(
            f"\U0001f614 Не удалось создать задачу генерации.\n"
            f"<b>Причина:</b> {friendly}\n"
            f"Ваш кредит <b>не списан</b>. Попробуйте ещё раз.",
            parse_mode="HTML",
        )
        set_user_state(
            chat_id,
            {"occasion": None, "style": None, "font": None, "text_mode": None,
             "ai_context": None, "addressee": None},
        )


async def process_kie_callback(
    task_id: str,
    state: str,
    result_json: dict,
    fail_msg: str | None,
    bot: Bot,
) -> bool:
    """Process Kie.ai callback and send postcard to user.
    
    Returns:
        True if processed successfully, False otherwise
    """
    from bot.database import get_pending_image_task
    
    # Get saved context
    task_data = get_pending_image_task(task_id)
    if not task_data:
        logger.warning(f"KIE CALLBACK: no data found for taskId={task_id}")
        return False
    
    chat_id = task_data["chat_id"]
    message_id = task_data["message_id"]
    payload = task_data["payload"]
    caption_for_db = task_data["caption_for_db"]
    
    logger.info(f"KIE CALLBACK: processing taskId={task_id}, state={state}, chat_id={chat_id}")
    
    try:
        if state == "success":
            result_urls = result_json.get("resultUrls", [])
            if not result_urls:
                logger.error(f"KIE CALLBACK: no resultUrls in response")
                await bot.edit_message_text(
                    "❌ Ошибка: нет URL изображения",
                    chat_id=chat_id,
                    message_id=message_id,
                )
                return False
            
            image_url = result_urls[0]
            logger.info(f"KIE CALLBACK: downloading image from {image_url}")
            
            # Download image
            image_bytes = await download_image(image_url)
            
            # Apply text overlay
            addressee = payload.get("addressee", payload["text_input"])
            occasion = payload["occasion"]
            font_name = payload.get("font", "Comfortaa")
            
            is_custom = occasion.startswith(CUSTOM_OCCASION_PREFIX)
            occasion_text = (
                occasion[len(CUSTOM_OCCASION_PREFIX):].strip()
                if is_custom
                else next(
                    (v for k, v in OCCASION_TEXT_MAP.items() if k in occasion), "праздник"
                )
            )
            
            text_to_draw = format_image_text(addressee, occasion_text, is_custom)
            logger.info(f"KIE CALLBACK: applying text '{text_to_draw}'")
            final_img_bytes = apply_text_to_image(image_bytes, text_to_draw, font_name)
            
            # Delete waiting message
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass
            
            # Send postcard
            pm_caption = (
                f"..., {caption_for_db}\n\n"
                f"\U0001f4a1 <b>Открытка готова!</b>\n"
                f"Чтобы отправить её с именем, напишите в любом чате:\n"
                f"<code>@pozdravish_bot Имя</code>"
            )
            
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(final_img_bytes, filename="postcard.jpg"),
                caption=pm_caption,
                parse_mode="HTML",
            )
            
            if msg and msg.photo:
                save_postcard(chat_id, msg.photo[-1].file_id, caption_for_db)
            
            increment_generations()
            add_credits(chat_id, -1)
            
            credits = get_credits(chat_id)
            await bot.send_message(
                chat_id=chat_id,
                text=f"Осталось бесплатных открыток: <b>{credits}</b>",
                parse_mode="HTML",
            )
            
            logger.info(f"KIE CALLBACK: postcard sent successfully to chat_id={chat_id}")
            return True
            
        elif state == "fail":
            logger.error(f"KIE CALLBACK: generation failed: {fail_msg}")
            await bot.edit_message_text(
                f"\U0001f614 Нейросеть не смогла сгенерировать открытку.\n"
                f"Ваш кредит <b>не списан</b>. Попробуйте ещё раз.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
            )
            return False
        
        else:
            logger.warning(f"KIE CALLBACK: unexpected state={state}")
            return False
            
    except Exception as e:
        logger.error(f"KIE CALLBACK: error processing callback: {e}", exc_info=True)
        try:
            await bot.edit_message_text(
                f"\U0001f614 Ошибка при обработке результата.\n"
                f"Ваш кредит <b>не списан</b>.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass
        return False
