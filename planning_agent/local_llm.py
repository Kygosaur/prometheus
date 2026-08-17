from __future__ import annotations

import ipaddress
import os
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def validate_loopback_url(base_url: str) -> str:
    """Allow loopback or explicitly configured internal inference hosts."""
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("LOCAL_LLM_BASE_URL must be an unauthenticated http:// loopback URL")
    allowed = {item.strip().casefold() for item in os.getenv("ALLOWED_LLM_HOSTS", "127.0.0.1").split(",")}
    try:
        address = ipaddress.ip_address(parsed.hostname)
        permitted = address.is_loopback
    except ValueError:
        permitted = parsed.hostname.casefold() in allowed
    if not permitted:
        if parsed.hostname and not _is_ip(parsed.hostname):
            raise ValueError("Use an explicit loopback IP or an explicit hostname in ALLOWED_LLM_HOSTS")
        raise ValueError("Remote LLM endpoints are disabled unless explicitly present in ALLOWED_LLM_HOSTS")
    return base_url.rstrip("/")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class LocalLLM:
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "kimi"
    timeout_seconds: int = 180

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", validate_loopback_url(self.base_url))
        if not self.model.strip():
            raise ValueError("A local model name is required")

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        response = self._post("/chat/completions", payload)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("Local LLM returned an unsupported response shape") from error
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Local LLM returned no text")
        return _strip_reasoning(content)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Local LLM HTTP error {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(
                "Cannot reach the local LLM. Start Ollama/vLLM on the configured loopback address."
            ) from error


def _strip_reasoning(text: str) -> str:
    """Hide model scratchpad tags while preserving the final user-facing answer."""
    patterns = (
        r"<think>.*?</think>",
        r"◁think▷.*?◁/think▷",
    )
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()
