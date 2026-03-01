import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image, ImageDraw, ImageFont

from bot.services import (
    format_image_text,
    apply_text_to_image,
    wrap_text,
    get_greeting_text_from_protalk,
)
from bot.config import OCCASION_TEXT_MAP


# ── helpers ────────────────────────────────────────────────────────────────────
def _patched_session(response_text: str):
    """Return a context manager that patches aiohttp.ClientSession."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=response_text)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=mock_resp)

    return patch("bot.services.aiohttp.ClientSession", return_value=mock_session)


# ── format_image_text ───────────────────────────────────────────────────────────
def test_format_image_text_custom():
    """Custom occasion always returns generic greeting."""
    assert format_image_text("Иван", "кастомный повод", is_custom=True) == "Иван, поздравляю!"


def test_format_image_text_standard():
    """Standard occasions are mapped to localised greeting strings."""
    assert format_image_text("Мария", "день рождения", is_custom=False) == "Мария, с Днём Рождения!"
    assert format_image_text("Алексей", "свадьбу", is_custom=False) == "Алексей, с Днём Свадьбы!"


def test_format_image_text_fallback():
    """Unknown occasion falls back to generic greeting."""
    assert format_image_text("Анна", "неизвестный праздник", is_custom=False) == "Анна, поздравляю!"


def test_format_image_text_all_standard_occasions():
    """All occasions in _OCCASION_DISPLAY_MAP are handled correctly."""
    cases = {
        "день рождения": "с Днём Рождения",
        "свадьбу": "с Днём Свадьбы",
        "рождение ребёнка": "с Новорожденным",
        "8 марта": "с 8 Марта",
        "завершение учёбы": "с Выпуском",
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


# ── get_greeting_text_from_protalk ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_greeting_text_fallback_on_network_error():
    """Returns fallback string when network raises an exception."""
    with patch("bot.services.aiohttp.ClientSession") as MockSession:
        instance = MagicMock()
        instance.__aenter__ = AsyncMock(side_effect=Exception("Network unreachable"))
        instance.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value = instance
        result = await get_greeting_text_from_protalk(
            "Иван", "день рождения", fallback="Поздравляю!"
        )
        assert result == "Поздравляю!"


@pytest.mark.asyncio
async def test_get_greeting_text_json_dict_text_key():
    """Correctly extracts 'text' field from JSON dict response."""
    with _patched_session('{"text": "Желаю счастья и здоровья!"}'):
        result = await get_greeting_text_from_protalk("Мария", "свадьбу")
        assert result == "Желаю счастья и здоровья!"


@pytest.mark.asyncio
async def test_get_greeting_text_plain_string_response():
    """Correctly handles raw plain-text response (no JSON wrapping)."""
    with _patched_session("Поздравляю от всей души!"):
        result = await get_greeting_text_from_protalk("Олег", "8 марта")
        assert result == "Поздравляю от всей души!"


@pytest.mark.asyncio
async def test_get_greeting_text_json_string_unwrap():
    """Correctly unwraps a JSON-encoded plain string (result is str, not dict)."""
    with _patched_session('"\u041fросто строка без словаря"'):
        result = await get_greeting_text_from_protalk("Олег", "8 марта")
        assert result == "Просто строка без словаря"
