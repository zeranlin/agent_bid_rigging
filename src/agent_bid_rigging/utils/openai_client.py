from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib import error, request


@dataclass(slots=True)
class OpenAIResponsesClient:
    api_key: str
    model: str = "gpt-5"
    base_url: str = "https://api.openai.com/v1/responses"
    timeout: int = 1800

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())

    @classmethod
    def from_env(cls) -> "OpenAIResponsesClient":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        model = os.environ.get("OPENAI_MODEL", "gpt-5").strip() or "gpt-5"
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1/responses").strip()
        timeout_raw = os.environ.get("OPENAI_TIMEOUT", "1800").strip() or "1800"
        try:
            timeout = max(1, int(timeout_raw))
        except ValueError:
            timeout = 1800
        return cls(
            api_key=api_key,
            model=model,
            base_url=_normalize_base_url(base_url),
            timeout=timeout,
        )

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        req = request.Request(self.base_url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI Responses API request failed: HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"OpenAI Responses API request failed: {exc.reason}") from exc

        text = data.get("output_text")
        if text:
            return text.strip()

        for output_item in data.get("output", []):
            for content_item in output_item.get("content", []):
                if content_item.get("type") in {"output_text", "text"}:
                    maybe_text = content_item.get("text", "")
                    if maybe_text:
                        return maybe_text.strip()
        raise RuntimeError("OpenAI Responses API returned no text output.")


def _normalize_base_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        return "https://api.openai.com/v1/responses"

    if "://" not in url:
        url = f"http://{url}"

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith("/responses"):
        final_path = path
    elif path.endswith("/v1"):
        final_path = f"{path}/responses"
    elif not path:
        final_path = "/v1/responses"
    else:
        final_path = f"{path}/responses"

    normalized = parsed._replace(path=final_path, params="", query="", fragment="")
    return normalized.geturl()
