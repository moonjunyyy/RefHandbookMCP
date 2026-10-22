"""Provider adapters over plain HTTP (httpx, already present through mcp): Anthropic Messages,
OpenAI Responses, Gemini generateContent, and a scripted `fake` for tests.

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

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1"
OPENAI_URL = "https://api.openai.com/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


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


class Adapter:
    name = ""

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

    def _headers(self, key: str, betas: list[str]) -> dict[str, str]:
        h = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
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
        body: dict[str, Any] = {
            "model": model, "max_tokens": opts.max_output, "system": [{"type": "text", "text": system}],
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools],
            "messages": history, "cache_control": {"type": "ephemeral"},
        }
        betas = []
        if opts.effort:
            body["output_config"] = {"effort": opts.effort}
        if opts.trim:
            betas.append("context-management-2025-06-27")
            body["context_management"] = {"edits": [{"type": "clear_tool_uses_20250919"}]}
        r = await http.post(f"{ANTHROPIC_URL}/messages", json=body, headers=self._headers(key, betas))
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
        d = _check(await http.get(f"{ANTHROPIC_URL}/models?limit=100", headers=self._headers(key, [])), "anthropic")
        return [m["id"] for m in d.get("data", [])]


# ── OpenAI (Responses API, stateless: store off, reasoning carried encrypted) ─────


class OpenAI(Adapter):
    name = "openai"

    def __init__(self) -> None:
        self.no_encrypted: set[str] = set()  # models that refused include=reasoning.encrypted_content

    def _headers(self, key: str) -> dict[str, str]:
        return {"authorization": f"Bearer {key}", "content-type": "application/json"}

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
            d = _check(await http.post(f"{OPENAI_URL}/responses", json=body, headers=self._headers(key)), "openai")
        except ProviderError as e:
            if e.status == 400 and "include" in body and ("encrypted" in str(e) or "reasoning" in str(e)):
                self.no_encrypted.add(model)
                body.pop("include")
                d = _check(await http.post(f"{OPENAI_URL}/responses", json=body, headers=self._headers(key)), "openai")
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
        d = _check(await http.get(f"{OPENAI_URL}/models", headers=self._headers(key)), "openai")
        return sorted(m["id"] for m in d.get("data", []))


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

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-goog-api-key": key, "content-type": "application/json"}

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
        d = _check(await http.post(f"{GEMINI_URL}/models/{model}:generateContent", json=body,
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
        d = _check(await http.get(f"{GEMINI_URL}/models?pageSize=200", headers=self._headers(key)), "gemini")
        return sorted(m["name"].removeprefix("models/") for m in d.get("models", [])
                      if "generateContent" in (m.get("supportedGenerationMethods") or []))


# ── fake (tests) ─────────────────────────────────────────────────────────


class Fake(Adapter):
    """A scripted provider. `policy(agent, history, system)` returns {"text": str, "calls": [(name,
    args), ...]}; the history entries are plain dicts {"role", "text"|"calls"|"results"}."""

    name = "fake"

    def __init__(self, policy: Callable[[dict[str, Any], list[Any], str], dict[str, Any]]):
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


ADAPTERS: dict[str, Callable[[], Adapter]] = {"anthropic": Anthropic, "openai": OpenAI, "gemini": Gemini}
