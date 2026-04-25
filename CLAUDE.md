# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Pozdravish Bot** is a Telegram bot that generates personalized greeting postcards. Users choose an occasion, art style, font, and message text; the bot calls Kie.ai to generate a background image, overlays the text with Pillow, and sends the result. Deployed on Vercel (serverless, 10-second timeout on hobby plan).

## Commands

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run local server (set WEBHOOK_URL to ngrok URL first)
python -m uvicorn api.index:app --reload --host 0.0.0.0 --port 8000
```

### Testing

```bash
pytest tests/ -v                                    # all tests
pytest tests/test_basic.py -v                       # single file
pytest tests/ --cov=bot --cov-report=term-missing   # with coverage
```

### Linting (CI gate)

```bash
flake8 . --max-line-length=127
```

### Deployment

Push to `main` — GitHub Actions runs lint + tests then auto-deploys to Vercel.

To register the Telegram webhook after deploy:
```
https://api.telegram.org/bot<TOKEN>/setWebhook?url=<VERCEL_URL>/api/webhook&secret_token=<WEBHOOK_SECRET>
```

## Architecture

```
Telegram ──webhook──▶ FastAPI (api/index.py)
                          │
                          ├─▶ POST /api/webhook      → Dispatcher → handlers.py
                          └─▶ POST /api/kie-callback  → services.process_kie_callback()

handlers.py   orchestrates user dialog state, calls services + database
services.py   external I/O: Kie.ai image tasks, ProTalk text, Pillow overlay
database.py   thin async wrapper around Upstash Redis REST API
keyboards.py  builds all InlineKeyboardMarkup objects
config.py     env vars, constants, prompt templates, font mappings
```

### Async Image Generation (Callback Pattern)

Vercel's 10-second limit means the bot cannot wait for Kie.ai (8–20 s). Instead:
1. `create_image_task_async()` submits the task with `callbackUrl=/api/kie-callback` and stores context in Redis (TTL 5 min).
2. The webhook handler returns immediately.
3. Kie.ai POSTs to `/api/kie-callback` when done.
4. `process_kie_callback()` downloads the image, applies text, sends to user, deducts one credit.

Credits are only deducted on successful delivery — never on task creation.

### Redis State Machine

All user dialog state is JSON in Upstash Redis (survives Vercel cold starts):

| Key pattern | Purpose |
|---|---|
| `user:{id}:credits` | Remaining credits |
| `user:{id}:state` | FSM state (occasion → style → font → …) |
| `user:{id}:pending_generation` | Saved payload when user needs to pay |
| `user:{id}:postcards` | Saved gallery (max 5, LIFO) |
| `pending_image:{task_id}` | Async callback context (TTL 5 min) |
| `stats:users` | Set of all user IDs (for broadcasts) |

### User Flow

```
/start → occasion → style → font → text_mode
                                       ├─▶ AI text → ai_context → addressee → generate
                                       └─▶ Custom  → custom_text → addressee → generate
```

If credits = 0, the flow saves `pending_generation` and shows YuKassa payment. After successful payment the saved payload is replayed.

## Key Implementation Notes

- **Redis mocking in tests**: `tests/conftest.py` patches `upstash_redis` at module level *before* importing any bot modules. This ordering is critical — do not change it.
- **Pillow font fallback chain**: Requested TTF → `fonts/Comfortaa-Regular.ttf` → Pillow default. Fonts live in `fonts/`.
- **Cyrillic mojibake fix**: `services.py` detects and re-encodes garbled UTF-8 in greeting text before overlay.
- **Text color**: Samples the center 40% of the generated image; picks light or dark text based on luminance.
- **Inline mode**: Shows 3 global template postcards (file_ids in config + Redis) + up to 5 personal saved postcards.
- **Referral rewards**: Inviter gets 2 credits, invitee gets 1 credit (hardcoded in `handlers.py`).
- **Free quota**: 3 credits per new user.
- **Admin commands**: `/stats`, `/broadcast`, `/reset`, `/clear_state` — gated by `ADMIN_ID` env var.

## Environment Variables

See `.env.example`. Required:

```
TELEGRAM_BOT_TOKEN
WEBHOOK_SECRET
WEBHOOK_URL          # base URL, no trailing slash (e.g. https://foo.vercel.app)
KIE_API_KEY
UPSTASH_REDIS_REST_URL
UPSTASH_REDIS_REST_TOKEN
ADMIN_ID
YUKASSA_PROVIDER_TOKEN
```
