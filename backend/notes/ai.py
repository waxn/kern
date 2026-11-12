"""Optional AI assistant.

Claude is called through the official Anthropic SDK. Other providers are reached through
their OpenAI-compatible chat endpoint. Nothing here runs unless a provider is configured.
"""
import json
import re
import urllib.error
import urllib.request

from .models import Setting

PROVIDERS = {
    "anthropic": {"label": "Anthropic (Claude)", "base_url": "", "model": "claude-opus-5-5"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": ""},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": ""},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": ""},
    "ollama": {"label": "Ollama (local)", "base_url": "http://host.docker.internal:11434/v1", "model": ""},
    "custom": {"label": "Other OpenAI-compatible", "base_url": "", "model": ""},
}
NEEDS_KEY = {"anthropic", "openai", "gemini", "openrouter"}
MAX_TOKENS = 16000
EFFORT_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5", "claude-haiku-5-5", "claude-opus-4-8", "claude-opus-4-7")


class AIError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ----------------------------------------------------------------- config


def _get(key: str) -> dict:
    v = Setting.objects.filter(key=key).values_list("value", flat=True).first()
    return v if isinstance(v, dict) else {}


def config() -> dict:
    cfg = _get("ai")
    provider = cfg.get("provider") if cfg.get("provider") in PROVIDERS else ""
    return {
        "provider": provider,
        "model": cfg.get("model") or (PROVIDERS[provider]["model"] if provider else ""),
        "base_url": cfg.get("base_url") or (PROVIDERS[provider]["base_url"] if provider else ""),
    }


def public_config() -> dict:
    """What the browser may see: never the key itself."""
    cfg = config()
    key = _get("ai_secret").get("api_key", "")
    p = cfg["provider"]
    ready = bool(p) and bool(cfg["model"]) and (bool(key) or p not in NEEDS_KEY) and (p == "anthropic" or bool(cfg["base_url"]))
    return {
        **cfg, "configured": ready, "has_key": bool(key), "key_hint": key[-4:] if len(key) > 8 else "",
        "web_search": ready,
        "providers": {k: {**v, "needs_key": k in NEEDS_KEY} for k, v in PROVIDERS.items()},
    }


def save_config(data: dict) -> dict:
    current = _get("ai")
    provider = data.get("provider", current.get("provider", ""))
    if provider and provider not in PROVIDERS:
        raise AIError("Unknown provider.")
    new = {
        "provider": provider,
        "model": str(data.get("model", current.get("model", "")) or "").strip()[:200],
        "base_url": str(data.get("base_url", current.get("base_url", "")) or "").strip().rstrip("/")[:500],
    }
    if new["base_url"] and not re.match(r"^https?://", new["base_url"]):
        raise AIError("The base URL must start with http:// or https://.")
    Setting.objects.update_or_create(key="ai", defaults={"value": new})
    if "api_key" in data:
        key = str(data["api_key"] or "").strip()
        if key:
            Setting.objects.update_or_create(key="ai_secret", defaults={"value": {"api_key": key}})
    if data.get("clear_key"):
        Setting.objects.filter(key="ai_secret").delete()
    return public_config()


# -------------------------------------------------------------- providers


def complete(system: str, prompt: str) -> str:
    cfg = config()
    key = _get("ai_secret").get("api_key", "")
    if not public_config()["configured"]:
        raise AIError("The AI assistant is not set up yet. Choose a provider in Settings → AI.", 409)
    if cfg["provider"] == "anthropic":
        return _anthropic(cfg, key, system, prompt)
    return _openai_compatible(cfg, key, system, prompt)


def _anthropic(cfg: dict, key: str, system: str, prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=300.0, max_retries=2)
    kwargs = dict(
        model=cfg["model"], max_tokens=MAX_TOKENS, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    # Current models think adaptively by default; effort is set explicitly
    # (Claude Opus 5.5 defaults to medium). Server-side fallbacks re-run a request
    # the safety classifiers decline on a suitable model instead of failing.
    if cfg["model"].startswith(EFFORT_MODELS):
        kwargs["output_config"] = {"effort": "medium"}
    use_fallbacks = cfg["model"] in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
    try:
        if use_fallbacks:
            msg = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            msg = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        raise AIError("Anthropic rejected the API key. Check it in Settings → AI.", 401)
    except anthropic.PermissionDeniedError:
        raise AIError("This API key is not allowed to use that model.", 403)
    except anthropic.NotFoundError:
        raise AIError(f"Model “{cfg['model']}” was not found. Check the model name in Settings → AI.", 404)
    except anthropic.RateLimitError:
        raise AIError("Anthropic's rate limit was reached. Try again in a minute.", 429)
    except anthropic.BadRequestError as e:
        raise AIError(f"Anthropic refused the request: {e.message}", 400)
    except anthropic.APIStatusError as e:
        raise AIError(f"Anthropic returned an error ({e.status_code}). Try again shortly.", 502)
    except anthropic.APIConnectionError:
        raise AIError("Could not reach Anthropic. Check the server's internet connection.", 502)
    if msg.stop_reason == "refusal":
        raise AIError("The model declined this request.", 422)
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if msg.stop_reason == "max_tokens":
        text += "\n\n(The answer was cut off at the length limit.)"
    return text


def _openai_compatible(cfg: dict, key: str, system: str, prompt: str) -> str:
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            data = json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read().decode())
            detail = (err.get("error") or {}).get("message") if isinstance(err.get("error"), dict) else err.get("error") or err.get("message") or ""
        except Exception:
            pass
        if e.code in (401, 403):
            raise AIError(f"The provider rejected the API key{': ' + detail if detail else '.'}", e.code)
        if e.code == 404:
            raise AIError(f"Not found — check the base URL and model name{': ' + detail if detail else '.'}", 404)
        if e.code == 429:
            raise AIError("The provider's rate limit was reached. Try again in a minute.", 429)
        raise AIError(f"The provider returned an error ({e.code}){': ' + detail if detail else '.'}", 502)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AIError(f"Could not reach {cfg['base_url']} ({getattr(e, 'reason', e)}).", 502)
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise AIError("The provider sent an answer Kern could not read.", 502)


# ------------------------------------------------------------------ tasks

WRITE_SYSTEM = """You are the writing assistant inside Kern, a personal notes app.
Reply with content to insert into the user's page, written in Markdown: headings (#, ##, ###),
paragraphs, "- " bullets (indent two spaces to nest), "1. " lists, "- [ ] " to-dos, > quotes,
``` code fences, $inline math$ and tables. Link to other pages with [[Page title]] only when the
user's notes mention that page. Write the content itself, with no preamble such as "Here is" and no
closing remarks. Match the language and tone of the user's notes."""

CARDS_SYSTEM = """You write flashcards for spaced repetition.
Return only a JSON array, no other text. Each item is one card:
{"kind": "basic", "front": "question", "back": "answer"}
or {"kind": "cloze", "front": "A sentence where the {{key term}} is hidden.", "back": ""}
or {"kind": "concept", "front": "Term", "back": "Definition"}.
Make each card test one idea, keep answers short, and avoid trivia the source does not support.
Write in the language of the source material."""

TEMPLATE_SYSTEM = """You design reusable page templates for a notes app.
Return only a JSON object, no other text:
{"title": "short template name", "icon": "one emoji", "markdown": "the template body"}
The body is Markdown: headings, bullets, "- [ ] " to-dos and short placeholder hints in
parentheses, e.g. "(what was decided)". Keep it practical and compact."""


def page_context(doc) -> tuple[str, bool]:
    from .porting import Exporter
    if doc is None:
        return "", False
    text = "\n".join(Exporter().md_blocks(list(doc.blocks.all())))
    limit = 400_000
    truncated = len(text) > limit
    return f"Current page: {doc.title or 'Untitled'}\n\n{text[:limit]}", truncated


def parse_json(text: str):
    """Find the first JSON array/object in a model reply (tolerates code fences)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    pairs = [("[", "]"), ("{", "}")]
    # Start with whichever bracket comes first, so "[ ]" inside a JSON string is not taken for the payload.
    pairs.sort(key=lambda p: text.find(p[0]) if text.find(p[0]) >= 0 else len(text))
    for opener, closer in pairs:
        start, end = text.find(opener), text.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start: end + 1])
            except ValueError:
                continue
    raise AIError("The model's answer was not in the expected format. Try again.", 502)
