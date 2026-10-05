"""Bounded non-streaming Ark chat completions; no secret or provider body in errors."""
import json
import socket
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from openform.config import Settings


@dataclass
class ModelFailure(Exception):
    code: str
    message: str
    unknown: bool = False
    retry_after: int | None = None
    usage: dict[str, int] | None = None
    raw_output: str | None = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def available(settings: Settings) -> bool:
    try:
        return settings.model_api_key_file is not None and bool(settings.model_api_key_file.read_text().strip())
    except OSError:
        return False


def complete(settings: Settings, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
    try:
        key = settings.model_api_key_file.read_text().strip() if settings.model_api_key_file else ""
    except OSError:
        key = ""
    if not key:
        raise ModelFailure("MODEL_UNAVAILABLE", "模型服务未配置，原草稿仍可使用或导入页面。")
    payload = json.dumps({"model": settings.model_id, "messages": messages, "stream": False,
                          "max_completion_tokens": settings.model_max_tokens,
                          "thinking": {"type": "disabled"}}, ensure_ascii=False).encode()
    request = Request(settings.model_base_url + "/chat/completions", data=payload,
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=settings.model_timeout) as response:
            body = response.read(2 * 1024 * 1024 + 1)
    except HTTPError as error:
        if error.code == 429:
            wait = error.headers.get("Retry-After", "30")
            raise ModelFailure("MODEL_RATE_LIMITED", "模型服务限流，任务等待后重试。",
                               retry_after=min(max(int(wait), 5), 300) if wait.isdigit() else 30) from None
        if error.code in {400, 401, 403, 404, 422}:
            raise ModelFailure("MODEL_REJECTED", "模型服务拒绝请求，请检查服务配置或修改要求；原草稿保留。") from None
        raise ModelFailure("MODEL_OUTCOME_UNKNOWN", "模型请求结果未知，可能产生费用。请核对供应商记录后重新创建任务。", unknown=True) from None
    except (URLError, TimeoutError, socket.timeout, OSError):
        raise ModelFailure("MODEL_OUTCOME_UNKNOWN", "模型连接或响应中断，结果和费用未确认；不自动重复调用。", unknown=True) from None
    if len(body) > 2 * 1024 * 1024:
        raise ModelFailure("MODEL_INVALID", "模型响应超过大小上限，未替换原草稿。", unknown=True)
    try:
        result = json.loads(body)
        if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
            raise ValueError("invalid response")
        choice = result["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("invalid choice")
        content = choice["message"]["content"]
        usage = result.get("usage", {})
        if not isinstance(usage, dict):
            raise ValueError("invalid usage")
        counters = {name: usage[name] for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if isinstance(usage.get(name), int) and not isinstance(usage[name], bool) and usage[name] >= 0}
    except (ValueError, KeyError, IndexError, TypeError):
        raise ModelFailure("MODEL_INVALID", "模型响应格式无效，费用未确认；原草稿保留。", unknown=True) from None
    if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content.strip():
        known_usage = "total_tokens" in counters
        raise ModelFailure("MODEL_INCOMPLETE", "模型未返回完整内容，原草稿保留。" +
                           ("已记录本次用量，可查看原输出后调整要求。" if known_usage else "费用未确认，不自动重复调用。"),
                           unknown=not known_usage, usage=counters, raw_output=content if isinstance(content, str) else None)
    return content, counters
