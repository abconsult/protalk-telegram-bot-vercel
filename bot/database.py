import json
from upstash_redis import Redis
from bot.config import FREE_CREDITS

# We assume Upstash Redis REST URL and token are in environment variables
# UPSTASH_REDIS_REST_URL
# UPSTASH_REDIS_REST_TOKEN
kv = Redis.from_env()


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def credits_key(user_id: int) -> str:
    return f"user:{user_id}:credits"

def state_key(user_id: int) -> str:
    return f"user:{user_id}:state"

def pending_key(user_id: int) -> str:
    return f"user:{user_id}:pending_generation"

def postcards_key(user_id: int) -> str:
    return f"user:{user_id}:postcards"

def template_file_id_key(template_id: str) -> str:
    """Global Redis key for a template's Telegram file_id."""
    return f"template:file_id:{template_id}"


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------

def get_credits(user_id: int) -> int:
    val = kv.get(credits_key(user_id))
    if val is None:
        kv.set(credits_key(user_id), FREE_CREDITS)
        return FREE_CREDITS
    return int(val)

def add_credits(user_id: int, amount: int) -> int:
    current = get_credits(user_id)
    new_val = current + amount
    kv.set(credits_key(user_id), new_val)
    return new_val


# ---------------------------------------------------------------------------
# User state (FSM stored in Redis — survives Vercel cold starts)
# ---------------------------------------------------------------------------

def set_user_state(user_id: int, state: dict):
    kv.set(state_key(user_id), json.dumps(state))

def get_user_state(user_id: int) -> dict:
    val = kv.get(state_key(user_id))
    if not val:
        return {}
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return {}
    if isinstance(val, dict):
        return val
    return {}


# ---------------------------------------------------------------------------
# Pending generation (saved when user runs out of credits mid-flow)
# ---------------------------------------------------------------------------

def save_pending(user_id: int, payload: dict):
    kv.set(pending_key(user_id), json.dumps(payload))

def pop_pending(user_id: int) -> dict:
    val = kv.get(pending_key(user_id))
    if val:
        kv.delete(pending_key(user_id))
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                pass
        if isinstance(val, dict):
            return val
    return None


# ---------------------------------------------------------------------------
# Statistics & Analytics
# ---------------------------------------------------------------------------

def record_new_user(user_id: int):
    kv.sadd("stats:users", user_id)

def get_all_users() -> list:
    """Returns a list of all user IDs that have started the bot."""
    return [int(uid) for uid in kv.smembers("stats:users")]

def is_user_exists(user_id: int) -> bool:
    return kv.sismember("stats:users", user_id)

def get_total_users() -> int:
    return kv.scard("stats:users")

def increment_generations():
    kv.incr("stats:generations")

def get_total_generations() -> int:
    val = kv.get("stats:generations")
    return int(val) if val else 0

def record_payment(amount_rub: int):
    kv.incrby("stats:revenue", amount_rub)

def get_total_revenue() -> int:
    val = kv.get("stats:revenue")
    return int(val) if val else 0


# ---------------------------------------------------------------------------
# User inline-mode postcards (personal gallery, max 5)
# ---------------------------------------------------------------------------

def save_postcard(user_id: int, file_id: str, caption: str):
    """Saves a generated postcard to the user's personal gallery (max 5)."""
    key = postcards_key(user_id)
    existing = kv.get(key)

    if existing:
        if isinstance(existing, str):
            try:
                cards = json.loads(existing)
            except Exception:
                cards = []
        else:
            cards = existing
    else:
        cards = []

    cards.insert(0, {"file_id": file_id, "caption": caption})
    cards = cards[:5]  # Keep only the most recent 5

    kv.set(key, json.dumps(cards))

def get_postcards(user_id: int) -> list:
    """Returns the user's saved postcards (newest first, max 5)."""
    key = postcards_key(user_id)
    val = kv.get(key)
    if val:
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return []
        return val
    return []


# ---------------------------------------------------------------------------
# Template postcards — global, not per-user
#
# Telegram file_ids for the 3 permanent template images are stored once
# (via /upload_templates admin command) and reused indefinitely.
# Key format:  template:file_id:{template_id}
#              e.g.  template:file_id:birthday
# ---------------------------------------------------------------------------

def set_template_file_id(template_id: str, file_id: str) -> None:
    """Persist a Telegram file_id for a template image.

    Called once by the /upload_templates admin command after the image
    is uploaded to Telegram.  The file_id is stable and never expires.
    """
    kv.set(template_file_id_key(template_id), file_id)


def get_template_file_id(template_id: str) -> str | None:
    """Return the stored Telegram file_id for a template, or None if not uploaded yet."""
    val = kv.get(template_file_id_key(template_id))
    # Upstash may return bytes or str depending on client version
    if isinstance(val, bytes):
        return val.decode()
    return val  # str or None


def get_all_template_file_ids() -> dict[str, str | None]:
    """Return a mapping of template_id → file_id for all templates.

    Useful for the /upload_templates status report and health checks.
    Values are None for templates that haven't been uploaded yet.
    """
    from bot.config import TEMPLATE_POSTCARDS
    return {
        tmpl["id"]: get_template_file_id(tmpl["id"])
        for tmpl in TEMPLATE_POSTCARDS
    }


def templates_are_ready() -> bool:
    """Return True only if all 3 template file_ids are present in Redis.

    Used by the inline handler to decide whether to show templates or
    fall back to the switch_pm prompt.
    """
    return all(get_all_template_file_ids().values())
