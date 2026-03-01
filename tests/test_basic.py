import pytest
from bot.services import format_image_text
from bot.config import OCCASION_TEXT_MAP

def test_format_image_text_custom():
    """Test formatting for custom occasion."""
    result = format_image_text("Иван", "кастомный повод", is_custom=True)
    assert result == "Иван, поздравляю!"

def test_format_image_text_standard():
    """Test formatting for standard occasions."""
    result = format_image_text("Мария", "день рождения", is_custom=False)
    assert result == "Мария, с Днём Рождения!"

    result = format_image_text("Алексей", "свадьбу", is_custom=False)
    assert result == "Алексей, с Днём Свадьбы!"

def test_format_image_text_fallback():
    """Test formatting for unknown occasion."""
    result = format_image_text("Анна", "неизвестный праздник", is_custom=False)
    assert result == "Анна, поздравляю!"

def test_occasion_map_integrity():
    """Ensure OCCASION_TEXT_MAP keys match the emojis in OCCASIONS list."""
    assert "🎂 День рождения" in OCCASION_TEXT_MAP
    assert OCCASION_TEXT_MAP["🎂 День рождения"] == "день рождения"
