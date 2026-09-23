"""Minimal connectivity check. Never prints credentials, prompts or provider bodies."""

import json
from openai import OpenAI, OpenAIError
from app.core.config import settings
from app.agent.tools import Registry
from app.services.application import Application

config = settings()
try:
    result = OpenAI(api_key=config.openai_api_key, timeout=25, max_retries=0).responses.create(
        model=config.openai_model,
        input="Reply with OK.",
        max_output_tokens=16,
        store=False,
        tools=Registry(Application(None, None)).definitions(),
        tool_choice="none",
    )
    print(json.dumps({"ok": True, "status": result.status}))
except OpenAIError as exc:
    print(
        json.dumps(
            {
                "ok": False,
                "type": type(exc).__name__,
                "status": getattr(exc, "status_code", None),
                "code": getattr(exc, "code", None),
            }
        )
    )
