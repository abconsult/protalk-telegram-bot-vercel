import pytest
from bot.services import format_image_text
from bot.config import OCCASION_TEXT_MAP, OCCASIONS

def test_format_image_text_logic():
    """Test that text is formatted correctly without addressee"""
    
    # Test standard occasion
    res = format_image_text("🎂 День рождения")
    assert "С Днём" in res
    assert "Рождения!" in res
    
    # Test another standard occasion
    res2 = format_image_text("🌸 8 марта")
    assert "С 8 Марта!" in res2

    # Test custom occasion with emoji
    res3 = format_image_text("✏️ Новый год")
    assert "Новый" in res3
    assert "Год" in res3

def test_occasion_mapping_completeness():
    """
    Ensure all standard occasions (except custom) are properly mapped 
    in OCCASION_TEXT_MAP so that AI prompts get the right theme.
    """
    standard_occasions = [occ for occ in OCCASIONS if not occ.startswith("✏️")]
    
    for occ in standard_occasions:
        assert occ in OCCASION_TEXT_MAP, f"Missing mapping for occasion: {occ}"
        assert isinstance(OCCASION_TEXT_MAP[occ], str)
        assert len(OCCASION_TEXT_MAP[occ]) > 0
