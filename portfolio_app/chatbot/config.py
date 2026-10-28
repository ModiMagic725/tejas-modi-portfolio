"""
Chatbot configuration. Everything is read from environment variables *at call time*
(not at import time), so Render's Environment tab and tests can change it without a code edit.

Nothing here is a secret except OPENAI_API_KEY, which is never logged, never returned
in a response and never rendered into a template.
"""
import os

MAX_MESSAGE_CHARS = 500         # longest visitor message accepted
MAX_BODY_BYTES = 8 * 1024       # reject bigger request bodies outright
MAX_HISTORY_TURNS = 6           # previous messages forwarded to the AI for context
MAX_HISTORY_CHARS = 400         # per previous message
MAX_REPLY_CHARS = 900           # longest AI reply we pass on to the browser
MAX_OUTPUT_TOKENS = 500         # cap on tokens the AI may generate


def _int(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def openai_api_key():
    return (os.environ.get('OPENAI_API_KEY') or '').strip()


def openai_model():
    # Default is the small, low-cost tier. Set OPENAI_MODEL in Render to use another model.
    return (os.environ.get('OPENAI_MODEL') or 'gpt-5.4-nano').strip()


def ai_enabled():
    return bool(openai_api_key())


def ai_timeout_seconds():
    return _int('CHATBOT_AI_TIMEOUT', 10)


# ---- rate limits (best effort: they live in Django's cache, see limits.py) ----
def chat_limit():            # any chatbot request, per visitor
    return _int('CHATBOT_RATE_LIMIT', 40), 300           # 40 requests / 5 minutes


def ai_visitor_limit():      # AI requests, per visitor
    return _int('CHATBOT_AI_PER_VISITOR', 6), 600        # 6 AI answers / 10 minutes


def ai_global_hourly_cap():  # AI requests across ALL visitors - protects the API bill
    return _int('CHATBOT_AI_HOURLY_CAP', 120), 3600


def ai_global_daily_cap():
    return _int('CHATBOT_AI_DAILY_CAP', 400), 86400
