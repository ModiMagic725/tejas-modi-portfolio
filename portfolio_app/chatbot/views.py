"""
POST /api/chatbot/  - the only server endpoint the widget uses.

Request  (application/json):
    {"intent": "skills"}                                  quick-reply button (never calls the AI)
    {"message": "...", "history": [{"role","text"}, ...]} typed question (history is optional)

Response (always JSON, always Cache-Control: no-store):
    200 {"ok": true, "source": "static|ai|fallback", "intent": "...", "reply": "plain text",
         "links": [{"label","url"}], "suggestions": [{"label","intent"}]}
    4xx {"ok": false, "error": {"code": "...", "message": "..."}}

Order of work for a typed message:
    1. validate input                     4. confident static match -> answer, no AI call
    2. block prompt-injection/secret asks 5. otherwise AI fallback, if configured and under the caps
    3. per-visitor rate limit             6. otherwise a friendly best-guess / suggestions reply

CSRF is enforced by Django's CsrfViewMiddleware (the view is NOT csrf_exempt). The visitor's
message is never stored or logged. Nothing here writes to the database.
"""
import json
import logging

from django.http import JsonResponse

from . import ai, config, intents, knowledge as kb, limits, music

logger = logging.getLogger(__name__)

_NOTICE_FAILED = ("I couldn't get a full answer to that just now. These pages and questions should "
                  "get you what you need:")
_NOTICE_BUSY = ("I'm getting a lot of questions right now, so I can only share the quick answers. "
                "These should help:")
_HEDGE = "I think you're asking about this:"


def _json(payload, status=200, headers=None):
    resp = JsonResponse(payload, status=status)
    resp['Cache-Control'] = 'no-store'
    for k, v in (headers or {}).items():
        resp[k] = v
    return resp


def _error(code, message, status, headers=None):
    return _json({'ok': False, 'error': {'code': code, 'message': message}}, status, headers)


def _safe_links(links):
    return [{'label': str(l['label'])[:60], 'url': l['url']} for l in links if l.get('url')]


def _reply_payload(reply, source, intent, text=None):
    return {
        'ok': True,
        'source': source,
        'intent': intent,
        'reply': text if text is not None else reply.text,
        'links': _safe_links(reply.links),
        'suggestions': [{'label': label, 'intent': iid} for label, iid in reply.suggestions[:4]],
    }


def _clean_history(raw):
    """Keep only well-formed {'role': user|assistant, 'text': str} items, trimmed and capped."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[-config.MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role, text = item.get('role'), item.get('text')
        if role in ('user', 'assistant') and isinstance(text, str) and text.strip():
            out.append({'role': role, 'text': ' '.join(text.split())[:config.MAX_HISTORY_CHARS]})
    return out


def chatbot_message(request):
    if request.method != 'POST':
        return _error('method_not_allowed', 'Use POST.', 405, {'Allow': 'POST'})
    if request.content_type != 'application/json':
        return _error('unsupported_media_type', 'Send JSON.', 415)

    try:
        length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        length = 0
    if length > config.MAX_BODY_BYTES:
        return _error('too_large', 'That request is too large.', 413)

    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return _error('bad_json', 'That request could not be read.', 400)
    if not isinstance(body, dict):
        return _error('bad_json', 'That request could not be read.', 400)

    intent_id = body.get('intent')
    message = body.get('message')
    if intent_id is not None and (not isinstance(intent_id, str) or intent_id not in intents.ALLOWED_INTENTS):
        return _error('bad_intent', 'Unknown quick reply.', 400)
    if message is not None and not isinstance(message, str):
        return _error('bad_message', 'Message must be text.', 400)
    message = ' '.join((message or '').split())          # collapse whitespace / newlines
    if not intent_id:
        if not message:
            return _error('empty_message', 'Please type a question.', 400)
        if len(message) > config.MAX_MESSAGE_CHARS:
            return _error('too_long', f'Please keep it under {config.MAX_MESSAGE_CHARS} characters.', 400)

    # Per-visitor rate limit for everything the widget does.
    visitor = limits.client_key(request)
    n, window = config.chat_limit()
    if limits.exceeded('chat', visitor, n, window):
        return _error('rate_limited', "You're sending messages quickly. Please wait a moment and try again.",
                      429, {'Retry-After': str(window)})

    data = kb.snapshot()

    # 1) Quick-reply button: always static.
    if intent_id:
        return _json(_reply_payload(intents.answer(intent_id, data), 'static', intent_id))

    # 2) Prompt-injection / secrets / admin requests: canned refusal, no AI call.
    if intents.is_blocked(message):
        return _json(_reply_payload(intents.blocked_reply(), 'static', 'blocked'))

    # 3) Confident static match: no AI call.
    m = intents.match(message)
    if m.confident:
        return _json(_reply_payload(intents.answer(m.intent, data), 'static', m.intent))

    # 4) AI fallback (optional).
    ai_attempted, ai_busy = False, False
    if ai.is_configured():
        vn, vw = config.ai_visitor_limit()
        hn, hw = config.ai_global_hourly_cap()
        dn, dw = config.ai_global_daily_cap()
        if (limits.exceeded('ai', visitor, vn, vw)
                or limits.exceeded('ai-hour', 'all', hn, hw)
                or limits.exceeded('ai-day', 'all', dn, dw)):
            ai_busy = True
        else:
            ai_attempted = True
            try:
                result = ai.answer(message, _clean_history(body.get('history')), data)
            except ai.AIError as exc:
                logger.info('Chatbot AI fallback unavailable: %s', exc.reason)
            except Exception:  # noqa: BLE001 - never turn an AI problem into an HTTP 500
                logger.exception('Chatbot AI fallback crashed')
            else:
                links = [kb.link(k) for k in result.pages]
                reply = intents.Reply(result.text, links=links,
                                      suggestions=intents._sugg('projects', 'hire', 'contact'))
                return _json(_reply_payload(reply, 'ai', 'ai'))

    # 5) Friendly static fallback: best guess if there was a real keyword signal, else suggestions.
    guess = m.intent if (m.intent != 'unknown' and m.score >= 3) else 'unknown'
    reply = intents.answer(guess, data)
    if ai_attempted or ai_busy:
        notice = _NOTICE_BUSY if ai_busy else _NOTICE_FAILED
        text = notice if guess == 'unknown' else f'{notice}\n\n{reply.text}'
        return _json(_reply_payload(reply, 'fallback', guess, text=text))
    if guess != 'unknown':
        return _json(_reply_payload(reply, 'static', guess, text=f'{_HEDGE}\n\n{reply.text}'))
    return _json(_reply_payload(reply, 'static', 'unknown'))


def chatbot_music(request):
    """GET /api/chatbot/music/ -> {"ok": true, "tracks": [{"id","lang","title","url"}, ...]}

    The list comes from the music folders (see chatbot/music.py). Public information only."""
    if request.method != 'GET':
        return _error('method_not_allowed', 'Use GET.', 405, {'Allow': 'GET'})
    if limits.exceeded('music', limits.client_key(request), 60, 300):
        return _error('rate_limited', 'Please try again in a moment.', 429, {'Retry-After': '300'})
    resp = _json({'ok': True, 'tracks': music.playlist()})
    resp['Cache-Control'] = 'public, max-age=120'
    return resp
