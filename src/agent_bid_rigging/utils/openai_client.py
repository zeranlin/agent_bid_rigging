from __future__ import annotations

import json
import os
import mimetypes
from pathlib import Path
from typing import Any
from dataclasses import dataclass
from base64 import b64encode
from urllib.parse import urlparse
from urllib import error, request


@dataclass(slots=True)
class OpenAIResponsesClient:
    api_key: str
    model: str = "gpt-5"
    base_url: str = "https://api.openai.com/v1/responses"
    timeout: int = 1800
    reasoning_effort: str | None = None
    no_thinking: bool = False

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
        reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT", "").strip() or None
        no_thinking = _env_truthy(os.environ.get("OPENAI_NO_THINKING", ""))
        try:
            timeout = max(1, int(timeout_raw))
        except ValueError:
            timeout = 1800
        return cls(
            api_key=api_key,
            model=model,
            base_url=_normalize_base_url(base_url),
            timeout=timeout,
            reasoning_effort=reasoning_effort,
            no_thinking=no_thinking,
        )

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        return self.generate_text(
            system_prompt=system_prompt,
            user_contents=[{"type": "input_text", "text": user_prompt}],
        )

    def generate_text(self, system_prompt: str, user_contents: list[dict[str, Any]]) -> str:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": user_contents},
            ],
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if self.no_thinking:
            payload["enable_thinking"] = False
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

    def image_content_from_path(self, path: str | Path) -> dict[str, str]:
        file_path = Path(path)
        mime_type, _ = mimetypes.guess_type(file_path.name)
        mime_type = mime_type or "image/png"
        encoded = b64encode(file_path.read_bytes()).decode("ascii")
        return {
            "type": "input_image",
            "image_url": f"data:{mime_type};base64,{encoded}",
        }

    def generate_chat_vision_text(self, system_prompt: str, user_prompt: str, image_path: str | Path) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": self.image_content_from_path(image_path)["image_url"]},
                        },
                    ],
                },
            ],
            "max_tokens": 1200,
        }
        if self.no_thinking:
            payload["enable_thinking"] = False
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        req = request.Request(_chat_completions_url(self.base_url), data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI chat completions request failed: HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"OpenAI chat completions request failed: {exc.reason}") from exc

        message = ((data.get("choices") or [{}])[0]).get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if item.get("type") == "text" and item.get("text"):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts).strip()

        reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()

        raise RuntimeError("Chat completions API returned no usable text output.")


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


def _chat_completions_url(responses_url: str) -> str:
    parsed = urlparse(responses_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/responses"):
        path = f"{path[: -len('/responses')]}/chat/completions"
    elif path.endswith("/v1"):
        path = f"{path}/chat/completions"
    elif not path:
        path = "/v1/chat/completions"
    else:
        path = f"{path}/chat/completions"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def _env_truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
