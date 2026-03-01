"""
Pytest configuration and shared fixtures.

IMPORTANT: upstash_redis is mocked at the TOP of this file, before any
bot.* import occurs. bot.database runs `kv = Redis.from_env()` at module
level, which would crash in CI without real UPSTASH_REDIS_REST_URL/TOKEN.
"""
import sys
import io
from unittest.mock import AsyncMock, MagicMock
import pytest
from PIL import Image

# ── Patch upstash_redis BEFORE any bot.* module is imported ──────────────────────
_redis_instance = MagicMock()
_redis_mock_module = MagicMock()
_redis_mock_module.Redis.from_env.return_value = _redis_instance
sys.modules.setdefault("upstash_redis", _redis_mock_module)
# ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_bot() -> MagicMock:
    """Minimal aiogram Bot mock."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    return bot


@pytest.fixture
def mock_message() -> MagicMock:
    """Minimal aiogram Message mock that returns a photo on answer_photo."""
    photo_mock = MagicMock()
    photo_mock.file_id = "test_file_id_001"
    sent_msg = MagicMock()
    sent_msg.photo = [photo_mock]

    msg = MagicMock()
    msg.chat = MagicMock(id=123456789)
    msg.from_user = MagicMock(id=123456789)
    msg.answer = AsyncMock(return_value=sent_msg)
    msg.answer_photo = AsyncMock(return_value=sent_msg)
    return msg


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Return bytes of a minimal valid 400x300 JPEG for image-processing tests."""
    img = Image.new("RGB", (400, 300), color=(120, 160, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
