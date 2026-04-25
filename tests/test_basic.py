import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image, ImageDraw, ImageFont

from bot.services import (
    format_image_text,
    apply_text_to_image,
    wrap_text,
    get_greeting_text,
)
from bot.config import OCCASION_TEXT_MAP


# ── helpers ────────────────────────────────────────────────────────────────────
def _patched_session(response_text: str):
    """Return a context manager that patches aiohttp.ClientSession.

    The ProTalk client uses ``async with session.post(...) as resp``, so we
    wire up mock_resp as an async context manager and attach it to .post().
    """
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=response_text)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.post = MagicMock(return_value=mock_resp)

    return patch("bot.services.aiohttp.ClientSession", return_value=mock_session)


# ── format_image_text ───────────────────────────────────────────────────────────
def test_format_image_text_custom():
    """Custom occasion always returns generic greeting."""
    assert format_image_text("Иван", "кастомный повод", is_custom=True) == "Иван, поздравляю!"


def test_format_image_text_standard():
    """Standard occasions are mapped to localised greeting strings.

    Spaces inside the display phrase are replaced with non-breaking spaces
    (\u00a0) so the overlay renderer keeps phrases on one line.
    """
    assert format_image_text("Мария", "день рождения", is_custom=False) == "Мария, с\u00a0Днём\u00a0Рождения!"
    assert format_image_text("Алексей", "свадьбу", is_custom=False) == "Алексей, с\u00a0Днём\u00a0Свадьбы!"


def test_format_image_text_fallback():
    """Unknown occasion falls back to generic greeting."""
    assert format_image_text("Анна", "неизвестный праздник", is_custom=False) == "Анна, поздравляю!"


def test_format_image_text_all_standard_occasions():
    """All occasions in _OCCASION_DISPLAY_MAP are handled correctly."""
    # Spaces inside display phrases are non-breaking (\u00a0) — see format_image_text
    cases = {
        "день рождения": "с\u00a0Днём\u00a0Рождения",
        "свадьбу": "с\u00a0Днём\u00a0Свадьбы",
        "рождение ребёнка": "с\u00a0Новорожденным",
        "8 марта": "с\u00a08\u00a0Марта",
        "завершение учёбы": "с\u00a0Выпуском",
    }
    for occasion, expected_suffix in cases.items():
        result = format_image_text("Тест", occasion, is_custom=False)
        assert result == f"Тест, {expected_suffix}!", f"Failed for '{occasion}'"


# ── OCCASION_TEXT_MAP integrity ──────────────────────────────────────────────────
def test_occasion_map_integrity():
    """Ensure OCCASION_TEXT_MAP keys and values are consistent."""
    assert "🎂 День рождения" in OCCASION_TEXT_MAP
    assert OCCASION_TEXT_MAP["🎂 День рождения"] == "день рождения"


def test_occasion_map_all_values_are_strings():
    """Every key and value in OCCASION_TEXT_MAP must be a non-empty string."""
    for key, value in OCCASION_TEXT_MAP.items():
        assert isinstance(key, str) and key, f"Key is empty: {key!r}"
        assert isinstance(value, str) and value, f"Value is empty for key {key!r}"


# ── apply_text_to_image ───────────────────────────────────────────────────────────
def test_apply_text_to_image_returns_valid_jpeg(sample_image_bytes):
    """apply_text_to_image must return valid JPEG bytes of the same dimensions."""
    result = apply_text_to_image(sample_image_bytes, "С Днём Рождения!", "Comfortaa")
    assert isinstance(result, bytes) and len(result) > 0
    img = Image.open(io.BytesIO(result))
    assert img.format == "JPEG"
    assert img.size == (400, 300)


def test_apply_text_to_image_unknown_font_fallback(sample_image_bytes):
    """apply_text_to_image must not raise even if the requested font is missing."""
    result = apply_text_to_image(sample_image_bytes, "Тест", "НесуществующийШрифт")
    assert isinstance(result, bytes) and len(result) > 0


def test_apply_text_to_image_multiline(sample_image_bytes):
    """apply_text_to_image handles multiline text without raising."""
    result = apply_text_to_image(sample_image_bytes, "Строка 1\nСтрока 2", "Comfortaa")
    assert isinstance(result, bytes) and len(result) > 0


# ── wrap_text ─────────────────────────────────────────────────────────────────────
def test_wrap_text_short_line_no_wrap():
    """A short line that fits in max_width is returned unchanged."""
    img = Image.new("RGB", (400, 100))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    assert wrap_text("Hi", font, 400, draw) == "Hi"


def test_wrap_text_forces_newline():
    """Long text is split into multiple lines when max_width is small."""
    img = Image.new("RGB", (400, 100))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    long_text = "один два три четыре пять шесть семь восемь"
    result = wrap_text(long_text, font, 40, draw)
    assert "\n" in result


# ── get_greeting_text (OpenRouter) ───────────────────────────────────────────────
def _openrouter_response(text: str) -> str:
    """Build a minimal OpenAI-compatible Chat Completions JSON response."""
    import json as _json
    return _json.dumps({
        "choices": [{"message": {"content": text}}]
    })


@pytest.mark.asyncio
async def test_get_greeting_text_fallback_on_network_error():
    """Returns fallback string when network raises an exception."""
    with patch("bot.services.aiohttp.ClientSession") as MockSession:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(side_effect=Exception("Network unreachable"))
        instance.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value = instance
        result = await get_greeting_text(
            "Иван", "день рождения", fallback="Поздравляю!"
        )
        assert result == "Поздравляю!"


@pytest.mark.asyncio
async def test_get_greeting_text_success():
    """Correctly extracts text from OpenRouter Chat Completions response."""
    with _patched_session(_openrouter_response("Желаю счастья и здоровья!")):
        result = await get_greeting_text("Мария", "свадьбу")
        assert result == "Желаю счастья и здоровья!"


@pytest.mark.asyncio
async def test_get_greeting_text_fallback_on_non_200():
    """Returns fallback when OpenRouter responds with non-200 status."""
    mock_resp = MagicMock()
    mock_resp.status = 429
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.post = MagicMock(return_value=mock_resp)
    with patch("bot.services.aiohttp.ClientSession", return_value=mock_session):
        result = await get_greeting_text("Олег", "8 марта", fallback="Поздравляю!")
        assert result == "Поздравляю!"
