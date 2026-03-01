import json
from upstash_redis import Redis
from bot.config import FREE_CREDITS

# We assume Upstash Redis REST URL and token are in environment variables
# UPSTASH_REDIS_REST_URL
# UPSTASH_REDIS_REST_TOKEN
kv = Redis.from_env()

def credits_key(user_id: int) -> str:
    return f"user:{user_id}:credits"

def state_key(user_id: int) -> str:
    return f"user:{user_id}:state"

def pending_key(user_id: int) -> str:
    return f"user:{user_id}:pending_generation"

def postcards_key(user_id: int) -> str:
    return f"user:{user_id}:postcards"


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

def set_user_state(user_id: int, state: dict):
    # Ensure we store it as a JSON string so retrieval is consistent
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

def save_pending(user_id: int, payload: dict):
    kv.set(pending_key(user_id), json.dumps(payload))

def pop_pending(user_id: int) -> dict:
    val = kv.get(pending_key(user_id))
    if val:
        kv.delete(pending_key(user_id))
        if isinstance(val, str):
            try:
                return json.loads(val)
            except:
                pass
        if isinstance(val, dict):
            return val
    return None

# ---- Statistics & Analytics ----

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

# ---- Inline Mode Postcards ----

def save_postcard(user_id: int, file_id: str, caption: str):
    """Saves a generated postcard to the user's personal gallery (max 5)"""
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
    cards = cards[:5]  # Keep only the last 5
    
    kv.set(key, json.dumps(cards))

def get_postcards(user_id: int) -> list:
    """Returns the user's saved postcards"""
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
