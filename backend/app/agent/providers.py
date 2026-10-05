"""Provider transport only. Application tools and authorization stay in Registry."""

from dataclasses import dataclass
from typing import Protocol

import httpx

UNAVAILABLE = "The AI service is temporarily unavailable. Please retry shortly."
PERPLEXITY_ENDPOINT = "https://api.perplexity.ai/v1/agent"


class ProviderError(Exception):
    """Sanitized error; never carries provider bodies, headers or credentials."""

    def __init__(self, status=None):
        super().__init__(UNAVAILABLE)
        self.status = status


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: str
    call_id: str


@dataclass(frozen=True)
class Response:
    output: list[dict]
    calls: list[ToolCall]
    text: str


class AIProvider(Protocol):
    def generate(self, *, instructions, inputs, tools=None, schema=None) -> Response: ...


def parse_response(data):
    """Validate the entire envelope before allowing any application action."""
    if not isinstance(data, dict) or data.get("status") != "completed" or data.get("error"):
        raise ProviderError()
    output = data.get("output")
    if not isinstance(output, list):
        raise ProviderError()
    calls, parts, ids = [], [], set()
    for item in output:
        if not isinstance(item, dict):
            raise ProviderError()
        if item.get("status", "completed") != "completed":
            raise ProviderError()
        if item.get("type") == "function_call":
            if any(not isinstance(item.get(k), str) or not item[k] for k in ("name", "arguments", "call_id")):
                raise ProviderError()
            if item["call_id"] in ids:
                raise ProviderError()
            ids.add(item["call_id"])
            calls.append(ToolCall(item["name"], item["arguments"], item["call_id"]))
        elif item.get("type") == "message":
            if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                raise ProviderError()
            for part in item["content"]:
                if not isinstance(part, dict):
                    raise ProviderError()
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    parts.append(part["text"])
                elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                    parts.append(part["refusal"])
                else:
                    raise ProviderError()
        elif item.get("type") != "reasoning":
            # No hosted search, calendar, MCP, or other provider-executed tools.
            raise ProviderError()
    if not calls and not "".join(parts).strip():
        raise ProviderError()
    return Response(output, calls, "".join(parts))


class PerplexityProvider:
    def __init__(self, config, timeout=40):
        self.model = config.perplexity_model
        self.key = config.perplexity_api_key
        self.timeout = timeout

    def generate(self, *, instructions, inputs, tools=None, schema=None):
        # Explicit custom tools only, no presets/profiles or hosted tools. Search is opt-in.
        if any(tool.get("type") != "function" for tool in tools or []):
            raise ProviderError()
        payload = dict(
            model=self.model,
            instructions=instructions,
            input=inputs,
            tools=tools or [],
            store=False,
            max_output_tokens=1800,
        )
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": schema},
            }
        try:
            response = httpx.post(
                PERPLEXITY_ENDPOINT,
                headers={"Authorization": f"Bearer {self.key}"},
                json=payload,
                timeout=self.timeout,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ProviderError(response.status_code)
            return parse_response(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            raise ProviderError() from None


def get_provider(config, *, client=None, timeout=40) -> AIProvider:
    # Tests may inject a provider implementing the same transport-independent protocol.
    if client is not None:
        return client
    if not config.ai_configured:
        raise ProviderError()
    return PerplexityProvider(config, timeout=timeout)
