"""Opt-in live connectivity check. Never prints keys, prompts or provider bodies."""

import json
from app.agent.providers import ProviderError, get_provider
from app.core.config import settings


if __name__ == "__main__":
    try:
        result = get_provider(settings(), timeout=25).generate(
            instructions="Reply with OK. Do not use tools.", inputs="Connection check.", tools=[]
        )
        print(json.dumps({"ok": bool(result.text)}))
    except ProviderError as exc:
        print(json.dumps({"ok": False, "status": exc.status}))
