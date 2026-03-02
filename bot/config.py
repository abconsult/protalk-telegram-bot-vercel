import os

TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET       = os.getenv("WEBHOOK_SECRET", "")  # Used to secure Telegram Webhook endpoint
PROTALK_BOT_ID       = os.getenv("PROTALK_BOT_ID", "23141")
PROTALK_TOKEN        = os.getenv("PROTALK_TOKEN", "")
PROTALK_FUNCTION_ID  = os.getenv("PROTALK_FUNCTION_ID", "609")
YUKASSA_TOKEN        = os.getenv("YUKASSA_PROVIDER_TOKEN", "")
ADMIN_ID             = int(os.getenv("ADMIN_ID", "128247430"))

FREE_CREDITS = 3
MAX_CUSTOM_TEXT_LENGTH = 300  # Maximum characters allowed for custom greeting text

PACKAGES = {
    3:  {"rub": 90,  "amount": 9000,  "label": "Пакет: 3 открытки"},
    5:  {"rub": 150, "amount": 15000, "label": "Пакет: 5 открыток"},
    10: {"rub": 300, "amount": 30000, "label": "Пакет: 10 открыток"},
}

OCCASIONS = [
    "🎂 День рождения",
    "💍 Свадьба",
    "👶 Рождение ребёнка",
    "🌸 8 марта",
    "🎓 Завершение учёбы",
    "✏️ Свой повод",
]

STYLES = [
    "Акварель",
    "Масло",
    "Неон",
    "Пастель",
    "Винтаж",
    "Минимализм",
]

FONTS_LIST = [
    "Lobster",
    "Caveat",
    "Pacifico",
    "Comfortaa",
]

FONTS_FILES = {
    "Lobster":    "fonts/Lobster-Regular.ttf",
    "Caveat":     "fonts/Caveat-Regular.ttf",
    "Pacifico":   "fonts/Pacifico-Regular.ttf",
    "Comfortaa":  "fonts/Comfortaa-Regular.ttf",
}

# Map EXACTLY the strings from OCCASIONS list (with emojis) to the prompt themes
OCCASION_TEXT_MAP = {
    "🎂 День рождения": "день рождения",
    "💍 Свадьба":            "свадьбу",
    "👶 Рождение ребёнка":  "рождение ребёнка",
    "🌸 8 марта":             "8 марта",
    "🎓 Завершение учёбы":  "завершение учёбы",
}

STYLE_PROMPT_MAP = {
    "Акварель": (
        "Акварельный фон для дизайна. Тематика: подарки на {occasion}. "
        "По краям холста акварельные детализированные тематические элементы, символизирующие {occasion}. "
        "В самом центре большое абсолютно пустое пространство с фоном как фактура рисовальной бумаги. "
        "Без букв, без слов, без текста. Empty center, watercolor background, pure empty space, no text."
    ),
    "Масло": (
        "Классическая живопись маслом на холсте, фон для дизайна. Тематика: подарки на {occasion}. "
        "По краям холста детализированные тематические элементы, символизирующие {occasion}. "
        "Богатая текстура мазков, выразительные цвета. "
        "В центре - большой однотонный пустой участок фона с фактурой холста."
        "Строго без надписей и букв, без физических рамок для картин."
        "Oil painting background, blank empty center, no words, zero text, no picture frames, borderless."
    ),
    "Неон": (
        "Киберпанк неоновый фон. Тематика: подарки на {occasion}. "
        "По краям холста тематические элементы, символизирующие {occasion}. "
        "Светящиеся элементы по контуру фигурок на тёмном фоне. "
        "В центре - абсолютно тёмная пустая зона без элементов. "
        "Никаких неоновых вывесок, никаких букв и символов. Neon background, blank dark center, no text."
    ),
    "Пастель": (
        "Фон нарисованный сухой пастелью, мягкие мелки. Тематика: подарки на {occasion}. "
        "По краям холста детализированные тематические элементы, символизирующие {occasion}. "
        "Мягкие переходы цвета по краям изображения."
        "В центре полностью пустая светлая область с фактурой бумаги. "
        "Никакого текста. Pastel drawing background, blank paper center, no text, no words."
    ),
    "Винтаж": (
        "Старинный винтажный фон в стиле советских почтовых открыток. Тематика: подарки на {occasion}. "
        "По краям холста детализированные тематические элементы, символизирующие {occasion}. "
        "В центре - пустое место с нейтральным однотонным фоном. "
        "Без каллиграфии, без букв. Vintage retro background, empty blank center, no text, no letters."
    ),
    "Минимализм": (
        "Ультра-минималистичный фон. Тематика: подарки на {occasion}. "
        "По краям холста тематические элементы, символизирующие {occasion}. "
        "Очень мало деталей, много пустого пространства. "
        "Только пара аккуратных тематических элементов по краям и лаконичные геометрические линии. "
        "Строго без текста, чистый фон. Minimalist background, lots of negative space, no text."
    ),
}

# ---------------------------------------------------------------------------
# Template postcards — 3 permanent cards always available in inline mode.
#
# Как заполнить file_id:
#   1. Отправьте готовое изображение любым ботом (например, через @RawDataBot) или
#      перешлите фото в чат с основным ботом.
#   2. Скопируйте file_id из ответа Telegram и вставьте вместо заглушки "".
#   3. Шаблон с пустым file_id автоматически пропускается в inline-результатах.
#
# Формат caption: начинается со строчной буквы — inline-обработчик
# подставляет имя адресата перед ним:
#   есть имя  →  "Маша, {caption}"
#   нет имени →  "..., {caption}"
# ---------------------------------------------------------------------------
TEMPLATE_POSTCARDS = [
    {
        "id":      "march8-1",
        "title":   "🌸 8 Марта",
        # ↓↓↓ вставьте реальный Telegram file_id вместо пустой строки
        "file_id": "AgACAgIAAxkBAAEbpnFppV5mWs17NZ2rGUBJ2pbn599P0wAC1RRrG4CCMUkQdC8PG-lu0QEAAwIAA3gAAzoE",
        "caption": "поздравляю с 8 марта! "
                   "Желаю здоровья, счастья и исполнения всех желаний! 🎂",
    },
    {
        "id":      "march8-2",
        "title":   "🌸 8 Марта",
        # ↓↓↓ вставьте реальный Telegram file_id вместо пустой строки
        "file_id": "AgACAgIAAxkBAAEbpnVppV6jBRx5AXY4xIjYsP_d-FXUuwACdhVrG4CCMUmbjUVYL0djDQEAAwIAA20AAzoE",
        "caption": "поздравляю с прекрасным весенним праздником! "
                   "Желаю красоты, тепла и женского счастья! 🌸",
    },
    {
        "id":      "march8-3",
        "title":   "🌸 8 Марта",
        # ↓↓↓ вставьте реальный Telegram file_id вместо пустой строки
        "file_id": "AgACAgIAAxkBAAEbpndppV7QJdgEn1WIy5Gq1CqpsUK0ugACeBVrG4CCMUmsC5oRdnAPXwEAAwIAA3gAAzoE",
        "caption": "поздравляю с праздником Весны! "
                   "Пусть каждый день приносит радость и улыбки! 🎉",
    },
]
