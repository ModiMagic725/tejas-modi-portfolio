"""
Hybrid portfolio chatbot.

  intents.py    - static question/answer system (no API key, no network)
  knowledge.py  - verified profile facts + published portfolio data from the database
  ai.py         - optional AI fallback (OpenAI, isolated behind a small provider class)
  limits.py     - rate limiting / spend cap
  views.py      - the single JSON endpoint used by the widget
"""
