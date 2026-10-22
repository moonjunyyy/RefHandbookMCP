"""Provider adapters over plain HTTP (httpx, already present through mcp), one per wire format:
Anthropic Messages, OpenAI Responses, OpenAI Chat Completions (what most OpenAI-compatible servers
speak), Gemini generateContent; and a scripted `fake` for tests.

An adapter is built for a base URL: the provider's own, or a custom key's. The base URL runs up to
and including the version path, the part before `/messages`, `/responses`, `/chat/completions` or
`/models/<m>:generateContent` (https://api.anthropic.com/v1, http://localhost:11434/v1). A custom
endpoint's address is checked before every call (`check_endpoint`): https, and a public address,
unless the administrator lists the host in RHB_AGENT_PRIVATE_ENDPOINTS (a model server on the LAN).

Each adapter maps one neutral shape onto its API:

    history  — a list of provider-native entries, appended to and never edited (the transcript);
    user(t)  — the native entry for a user text;
    results  — the native entries answering every tool call of the last step (plus optional text,
               placed after the results: the append-only place for reminders and new mail);
    step()   — one model turn: returns the native entries to append, the text, the tool calls and
               the usage.

The provider's own turn is appended verbatim: Anthropic thinking blocks, OpenAI reasoning items
(with encrypted content; the store is off) and Gemini thought signatures go back exactly as they
came. Anthropic binds thinking blocks to the conversation prefix, so nothing earlier is ever
rewritten: trimming old tool output is the server's context editing there, and a digest starts a
new segment that replays no earlier thinking (docs/agents.md §5).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1"
OPENAI_URL = "https://api.openai.com/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}
# Claude API models that take the server-side refusal fallback (fallbacks: "default")
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
TRIM_BETA = "context-management-2025-06-27"


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]
    error: str | None = None  # the arguments did not parse


@dataclass
class Step:
    native: list[Any]
    text: str
    calls: list[ToolCall]
    usage: dict[str, int]
    stop: str
    refusal: bool = False


@dataclass
class Options:
    max_output: int = 16000
    effort: str | None = None
    trim: bool = False  # clear old tool results (Anthropic: server-side context editing)
    keep_results: int = 6  # with trim on the client side: tool results kept whole
    agent: dict[str, Any] = field(default_factory=dict)  # for the fake adapter


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int = 0, retryable: bool = False, retry_after: float | None = None,
                 auth: bool = False):
        super().__init__(message)
        self.status, self.retryable, self.retry_after, self.auth = status, retryable, retry_after, auth


def _check(r: httpx.Response, who: str) -> dict[str, Any]:
    if r.status_code == 200:
        return r.json()
    try:
        body = r.json()
        msg = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else str(body)[:500]
    except ValueError:
        msg = r.text[:500]
    ra = r.headers.get("retry-after")
    try:
        retry_after = float(ra) if ra else None
    except ValueError:
        retry_after = None
    raise ProviderError(f"{who} {r.status_code}: {msg}", status=r.status_code, retryable=r.status_code in RETRYABLE,
                        retry_after=retry_after, auth=r.status_code in (401, 403))


def _args(raw: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(raw, dict):
        return raw, None
    try:
        v = json.loads(raw or "{}")
    except (TypeError, ValueError) as e:
        return {}, f"arguments are not valid JSON: {e}"
    return (v, None) if isinstance(v, dict) else ({}, "arguments must be a JSON object")


class EndpointRefused(ProviderError):
    pass


def _private_ok() -> set[str]:
    return {x.strip().lower() for x in os.environ.get("RHB_AGENT_PRIVATE_ENDPOINTS", "").split(",") if x.strip()}


async def check_endpoint(url: str) -> None:
    """Refuse a custom endpoint that is not https to a public address, unless its host (or host:port)
    is in RHB_AGENT_PRIVATE_ENDPOINTS. Checked on every call: a name can resolve elsewhere later."""
    from urllib.parse import urlparse

    u = urlparse(url)
    host = (u.hostname or "").lower()
    port = u.port or (443 if u.scheme == "https" else 80)
    allow = _private_ok()
    if host in allow or f"{host}:{port}" in allow:
        return
    if u.scheme != "https":
        raise EndpointRefused(f"{host}: plain http only to hosts the administrator lists in "
                              "RHB_AGENT_PRIVATE_ENDPOINTS", status=0)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise EndpointRefused(f"{host}: does not resolve ({e})", status=0, retryable=True) from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise EndpointRefused(f"{host} resolves to {ip}, not a public address; the administrator can "
                                  "allow it in RHB_AGENT_PRIVATE_ENDPOINTS", status=0)


class Adapter:
    name = ""
    default_url = ""

    def __init__(self, base_url: str | None = None):
        self.base = (base_url or self.default_url).rstrip("/")
        self.custom = bool(base_url) and self.base != self.default_url

    def user(self, text: str) -> list[Any]:
        raise NotImplementedError

    def results(self, results: list[tuple[ToolCall, str, bool]], extra: str | None = None) -> list[Any]:
        raise NotImplementedError

    async def step(self, http: httpx.AsyncClient, key: str, model: str, system: str, tools: list[ToolSpec],
                   history: list[Any], opts: Options) -> Step:
        raise NotImplementedError

    async def models(self, http: httpx.AsyncClient, key: str) -> list[str]:
        raise NotImplementedError


# ── Anthropic ────────────────────────────────────────────────────────────


class Anthropic(Adapter):
    name = "anthropic"
    default_url = ANTHROPIC_URL

    def __init__(self, base_url: str | None = None):
        super().__init__(base_url)
        self.no_fallback: set[str] = set()

    def _headers(self, key: str, betas: list[str]) -> dict[str, str]:
        h = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
        if key:
            h["x-api-key"] = key
        if betas:
            h["anthropic-beta"] = ",".join(betas)
        return h

    def user(self, text: str) -> list[Any]:
        return [{"role": "user", "content": [{"type": "text", "text": text}]}]

    def results(self, results: list[tuple[ToolCall, str, bool]], extra: str | None = None) -> list[Any]:
        content: list[dict[str, Any]] = [
            {"type": "tool_result", "tool_use_id": c.id, "content": text, **({"is_error": True} if err else {})}
            for c, text, err in results]
        if extra:
            content.append({"type": "text", "text": extra})
        return [{"role": "user", "content": content}]

    async def step(self, http, key, model, system, tools, history, opts):  # noqa: ANN001
        # the system prompt and the tools never change within an agent's life, the history is only
        # appended to: top-level cache_control caches the whole prefix up to the last block
        body: dict[str, Any] = {
            "model": model, "max_tokens": opts.max_output, "system": [{"type": "text", "text": system}],
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools],
            "messages": history, "cache_control": {"type": "ephemeral"},
        }
        betas = []
        if opts.effort:
            body["output_config"] = {"effort": opts.effort}
        if opts.trim:
            betas.append(TRIM_BETA)
            body["context_management"] = {"edits": [{"type": "clear_tool_uses_20250919"}]}
        if not self.custom and model in FALLBACK_MODELS and model not in self.no_fallback:
            betas.append(FALLBACK_BETA)  # a safety decline is retried on another model in the same call
            body["fallbacks"] = "default"
        r = await http.post(f"{self.base}/messages", json=body, headers=self._headers(key, betas))
        if r.status_code == 400 and "fallbacks" in body and "fallback" in r.text:
            self.no_fallback.add(model)  # not offered to this account or model: go on without it
            body.pop("fallbacks")
            betas.remove(FALLBACK_BETA)
            r = await http.post(f"{self.base}/messages", json=body, headers=self._headers(key, betas))
        d = _check(r, "anthropic")
        content = d.get("content") or []
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in content if b.get("type") == "tool_use"]
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        u = d.get("usage") or {}
        usage = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                 "cache_read": u.get("cache_read_input_tokens") or 0,
                 "cache_write": u.get("cache_creation_input_tokens") or 0}
        stop = d.get("stop_reason") or ""
        return Step([{"role": "assistant", "content": content}], text, calls, usage, stop, refusal=stop == "refusal")

    async def models(self, http, key):  # noqa: ANN001
        d = _check(await http.get(f"{self.base}/models?limit=100", headers=self._headers(key, [])), "anthropic")
        return [m["id"] for m in d.get("data", [])]


# ── OpenAI (Responses API, stateless: store off, reasoning carried encrypted) ─────


def _bearer(key: str) -> dict[str, str]:
    return {"content-type": "application/json", **({"authorization": f"Bearer {key}"} if key else {})}


class OpenAI(Adapter):
    name = "openai"
    default_url = OPENAI_URL

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url)
        self.no_encrypted: set[str] = set()  # models that refused include=reasoning.encrypted_content

    def _headers(self, key: str) -> dict[str, str]:
        return _bearer(key)

    def user(self, text: str) -> list[Any]:
        return [{"role": "user", "content": [{"type": "input_text", "text": text}]}]

    def results(self, results, extra=None):  # noqa: ANN001
        out: list[Any] = [{"type": "function_call_output", "call_id": c.id, "output": text} for c, text, _ in results]
        if extra:
            out += self.user(extra)
        return out

    @staticmethod
    def _replayable(item: dict[str, Any]) -> dict[str, Any]:
        """With the store off, item ids refer to nothing on the server: keep them only on reasoning
        items (which carry their encrypted content)."""
        if item.get("type") == "reasoning":
            return item
        return {k: v for k, v in item.items() if k not in ("id", "status")}

    def _render(self, history: list[Any], opts: Options) -> list[Any]:
        items = [self._replayable(i) for i in history]
        if not opts.trim:
            return items
        outs = [i for i, it in enumerate(items) if it.get("type") == "function_call_output"]
        cut = set(outs[:-opts.keep_results]) if len(outs) > opts.keep_results * 2 else set()
        return [{**it, "output": "[older tool output elided; re-run or read the file if needed]"} if i in cut else it
                for i, it in enumerate(items)]

    async def step(self, http, key, model, system, tools, history, opts):  # noqa: ANN001
        body: dict[str, Any] = {
            "model": model, "instructions": system, "input": self._render(history, opts), "store": False,
            "tools": [{"type": "function", "name": t.name, "description": t.description, "parameters": t.schema,
                       "strict": False} for t in tools],
            "max_output_tokens": opts.max_output,
        }
        if opts.effort:
            body["reasoning"] = {"effort": opts.effort}
        if model not in self.no_encrypted:
            body["include"] = ["reasoning.encrypted_content"]
        try:
            d = _check(await http.post(f"{self.base}/responses", json=body, headers=self._headers(key)), "openai")
        except ProviderError as e:
            if e.status == 400 and "include" in body and ("encrypted" in str(e) or "reasoning" in str(e)):
                self.no_encrypted.add(model)
                body.pop("include")
                d = _check(await http.post(f"{self.base}/responses", json=body, headers=self._headers(key)), "openai")
            else:
                raise
        output = d.get("output") or []
        calls, texts, refusal = [], [], False
        for it in output:
            if it.get("type") == "function_call":
                args, err = _args(it.get("arguments"))
                calls.append(ToolCall(it["call_id"], it["name"], args, err))
            elif it.get("type") == "message":
                for c in it.get("content") or []:
                    if c.get("type") == "output_text":
                        texts.append(c.get("text", ""))
                    elif c.get("type") == "refusal":
                        refusal = True
                        texts.append(c.get("refusal", ""))
        u = d.get("usage") or {}
        usage = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                 "cache_read": (u.get("input_tokens_details") or {}).get("cached_tokens", 0),
                 "reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0)}
        stop = d.get("status", "")
        if stop == "incomplete":
            stop = "incomplete:" + str((d.get("incomplete_details") or {}).get("reason", ""))
        return Step(list(output), "".join(texts), calls, usage, stop, refusal=refusal)

    async def models(self, http, key):  # noqa: ANN001
        d = _check(await http.get(f"{self.base}/models", headers=self._headers(key)), "openai")
        return sorted(m["id"] for m in d.get("data", []))


# ── OpenAI Chat Completions (most OpenAI-compatible servers: vLLM, Ollama, OpenRouter, …) ─────


class OpenAIChat(Adapter):
    name = "openai-chat"
    default_url = OPENAI_URL

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url)
        self.completion_param: set[str] = set()  # models that want max_completion_tokens, not max_tokens

    def user(self, text: str) -> list[Any]:
        return [{"role": "user", "content": text}]

    def results(self, results, extra=None):  # noqa: ANN001
        out: list[Any] = [{"role": "tool", "tool_call_id": c.id, "content": text} for c, text, _ in results]
        if extra:
            out += self.user(extra)
        return out

    def _render(self, history: list[Any], opts: Options) -> list[Any]:
        if not opts.trim:
            return history
        outs = [i for i, m in enumerate(history) if m.get("role") == "tool"]
        cut = set(outs[:-opts.keep_results]) if len(outs) > opts.keep_results * 2 else set()
        return [{**m, "content": "[older tool output elided; re-run or read the file if needed]"} if i in cut else m
                for i, m in enumerate(history)]

    async def step(self, http, key, model, system, tools, history, opts):  # noqa: ANN001
        body: dict[str, Any] = {
            "model": model, "messages": [{"role": "system", "content": system}, *self._render(history, opts)],
            "tools": [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                        "parameters": t.schema}} for t in tools],
        }
        body["max_completion_tokens" if model in self.completion_param else "max_tokens"] = opts.max_output
        if opts.effort:
            body["reasoning_effort"] = opts.effort
        url = f"{self.base}/chat/completions"
        r = await http.post(url, json=body, headers=_bearer(key))
        if r.status_code == 400 and "max_tokens" in body and "max_completion_tokens" in r.text:
            self.completion_param.add(model)
            body["max_completion_tokens"] = body.pop("max_tokens")
            r = await http.post(url, json=body, headers=_bearer(key))
        d = _check(r, "openai-chat")
        choice = (d.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls, native_calls = [], []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            cid = tc.get("id") or f"call-{len(history)}-{i}"
            args, err = _args(fn.get("arguments"))
            calls.append(ToolCall(cid, fn.get("name", ""), args, err))
            native_calls.append({"id": cid, "type": "function",
                                 "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments") or "{}"}})
        text = msg.get("content") or ""
        if isinstance(text, list):  # some servers return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        # only the fields every server accepts back (a reasoning_content echoed back is refused by some)
        entry: dict[str, Any] = {"role": "assistant", "content": text or None}
        if native_calls:
            entry["tool_calls"] = native_calls
        u = d.get("usage") or {}
        usage = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0),
                 "cache_read": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0}
        stop = choice.get("finish_reason") or ""
        return Step([entry], text, calls, usage, stop, refusal=bool(msg.get("refusal")) or stop == "content_filter")

    async def models(self, http, key):  # noqa: ANN001
        d = _check(await http.get(f"{self.base}/models", headers=_bearer(key)), "openai-chat")
        return sorted(m["id"] for m in d.get("data", []) if isinstance(m, dict) and "id" in m)


# ── Gemini ───────────────────────────────────────────────────────────────

_GEMINI_SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable"}


def gemini_schema(s: Any) -> Any:
    """JSON Schema → the OpenAPI subset generateContent accepts (upper-case types, no extras)."""
    if not isinstance(s, dict):
        return s
    out: dict[str, Any] = {}
    for k, v in s.items():
        if k not in _GEMINI_SCHEMA_KEYS:
            continue
        if k == "type":
            out[k] = (v[0] if isinstance(v, list) else v).upper()
        elif k == "properties":
            out[k] = {name: gemini_schema(sub) for name, sub in v.items()}
        elif k == "items":
            out[k] = gemini_schema(v)
        else:
            out[k] = v
    return out


class Gemini(Adapter):
    name = "gemini"
    default_url = GEMINI_URL

    def _headers(self, key: str) -> dict[str, str]:
        return {"content-type": "application/json", **({"x-goog-api-key": key} if key else {})}

    def user(self, text: str) -> list[Any]:
        return [{"role": "user", "parts": [{"text": text}]}]

    def results(self, results, extra=None):  # noqa: ANN001
        parts: list[dict[str, Any]] = []
        for c, text, err in results:
            fr: dict[str, Any] = {"name": c.name, "response": {"error" if err else "output": text}}
            if not c.id.startswith("gemini-"):
                fr["id"] = c.id
            parts.append({"functionResponse": fr})
        if extra:
            parts.append({"text": extra})
        return [{"role": "user", "parts": parts}]

    def _render(self, history: list[Any], opts: Options) -> list[Any]:
        if not opts.trim:
            return history
        idx = [(i, j) for i, c in enumerate(history) for j, p in enumerate(c.get("parts") or [])
               if "functionResponse" in p]
        if len(idx) <= opts.keep_results * 2:
            return history
        cut = set(idx[:-opts.keep_results])
        out = []
        for i, c in enumerate(history):
            parts = []
            for j, p in enumerate(c.get("parts") or []):
                if (i, j) in cut:
                    fr = dict(p["functionResponse"])
                    fr["response"] = {"output": "[older tool output elided; re-run or read the file if needed]"}
                    p = {**p, "functionResponse": fr}
                parts.append(p)
            out.append({**c, "parts": parts})
        return out

    async def step(self, http, key, model, system, tools, history, opts):  # noqa: ANN001
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]}, "contents": self._render(history, opts),
            "tools": [{"functionDeclarations": [{"name": t.name, "description": t.description,
                                                 "parameters": gemini_schema(t.schema)} for t in tools]}],
            "generationConfig": {"maxOutputTokens": opts.max_output},
        }
        if opts.effort:
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": opts.effort}
        d = _check(await http.post(f"{self.base}/models/{model}:generateContent", json=body,
                                   headers=self._headers(key)), "gemini")
        cands = d.get("candidates") or []
        u = d.get("usageMetadata") or {}
        usage = {"input": u.get("promptTokenCount", 0), "output": u.get("candidatesTokenCount", 0),
                 "cache_read": u.get("cachedContentTokenCount", 0), "reasoning": u.get("thoughtsTokenCount", 0)}
        if not cands:
            reason = (d.get("promptFeedback") or {}).get("blockReason", "no candidates")
            return Step([], f"(blocked: {reason})", [], usage, str(reason), refusal=True)
        content = cands[0].get("content") or {"role": "model", "parts": []}
        content.setdefault("role", "model")
        calls, texts = [], []
        for i, p in enumerate(content.get("parts") or []):
            if "functionCall" in p:
                fc = p["functionCall"]
                calls.append(ToolCall(fc.get("id") or f"gemini-{i}", fc["name"], fc.get("args") or {}))
            elif "text" in p and not p.get("thought"):
                texts.append(p["text"])
        stop = cands[0].get("finishReason", "")
        return Step([content], "".join(texts), calls, usage, stop,
                    refusal=stop in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"))

    async def models(self, http, key):  # noqa: ANN001
        d = _check(await http.get(f"{self.base}/models?pageSize=200", headers=self._headers(key)), "gemini")
        return sorted(m["name"].removeprefix("models/") for m in d.get("models", [])
                      if "generateContent" in (m.get("supportedGenerationMethods") or []))


# ── fake (tests) ─────────────────────────────────────────────────────────


class Fake(Adapter):
    """A scripted provider. `policy(agent, history, system)` returns {"text": str, "calls": [(name,
    args), ...]}; the history entries are plain dicts {"role", "text"|"calls"|"results"}."""

    name = "fake"

    def __init__(self, policy: Callable[[dict[str, Any], list[Any], str], dict[str, Any]], base_url: str | None = None):
        super().__init__(base_url)
        self.policy = policy
        self.n = 0

    def user(self, text):  # noqa: ANN001
        return [{"role": "user", "text": text}]

    def results(self, results, extra=None):  # noqa: ANN001
        return [{"role": "user", "results": [{"id": c.id, "name": c.name, "text": t, "error": e} for c, t, e in results],
                 "text": extra or ""}]

    async def step(self, http, key, model, system, tools, history, opts):  # noqa: ANN001
        out = self.policy(opts.agent, history, system)
        calls = []
        for name, args in out.get("calls", []):
            self.n += 1
            calls.append(ToolCall(f"call{self.n}", name, args))
        entry = {"role": "assistant", "text": out.get("text", ""), "calls": [c.__dict__ for c in calls]}
        n_in = sum(len(json.dumps(h)) for h in history) // 4
        return Step([entry], out.get("text", ""), calls, {"input": n_in, "output": 10}, "tool_use" if calls else "end")

    async def models(self, http, key):  # noqa: ANN001
        return ["fake"]


# by wire format (keys.FORMATS)
ADAPTERS: dict[str, Callable[..., Adapter]] = {"anthropic": Anthropic, "openai": OpenAI, "openai-chat": OpenAIChat,
                                               "gemini": Gemini}


def adapter(fmt: str, base_url: str = "") -> Adapter:
    try:
        return ADAPTERS[fmt](base_url or None)
    except KeyError as e:
        raise ProviderError(f"no adapter for format {fmt!r}") from e
