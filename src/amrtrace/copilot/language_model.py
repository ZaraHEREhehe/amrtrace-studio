"""The optional language-model layer of the Review Copilot (task I-19, D-27).

Templates always come first. A language model may only reword them, sentence by sentence: it gets the template
sentences and must return the same number, in the same order. A reworded sentence keeps the sources of its template,
and it is kept only if it carries exactly the identifiers and numbers of its template; otherwise the template sentence
is used. Any failure (no model configured, no network, a bad answer) leaves the template text, so the copilot always
works offline.

Order of preference, all optional and configured in the environment (.env, never the repository):
    AMRTRACE_COPILOT_LOCAL_MODEL   a local model served by Ollama (AMRTRACE_COPILOT_LOCAL_URL, default port 11434)
    GROQ_API_KEY                   the free hosted fallback (AMRTRACE_COPILOT_HOSTED_MODEL to pick the model)
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from .templates import CopilotSummary, Sentence

DEFAULT_LOCAL_URL = "http://127.0.0.1:11434"
HOSTED_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_HOSTED_MODEL = "llama-3.1-8b-instant"
TIMEOUT_SECONDS = 20
# a plain name of our own: some hosted APIs (Groq's, behind Cloudflare) answer 403 to Python's default "Python-urllib"
USER_AGENT = "amrtrace-studio-copilot/1.0"

INSTRUCTIONS = (
    "You reword short factual sentences about an antimicrobial-resistance case for a reviewer. Rewrite each sentence "
    "in plain English. Keep every identifier, code, version and number exactly as written. Do not add, remove or "
    "guess any fact. Answer with JSON only: {\"sentences\": [...]} with exactly as many sentences as given, in the "
    "same order."
)

# identifiers and numbers: anything with a digit, and stored codes written in capitals
_TOKEN = re.compile(r"[A-Za-z0-9_.|:<>=+\-]*\d[A-Za-z0-9_.|:<>=+\-]*|\b[A-Z][A-Z0-9_]{2,}\b")


class Rewriter(Protocol):
    name: str

    def rewrite(self, sentences: Sequence[str]) -> list[str]: ...


class RewriteFailed(Exception):
    pass


def facts(text: str) -> set[str]:
    return {token.strip(".,;:()") for token in _TOKEN.findall(text)} - {""}


def keeps_facts(template: str, reworded: str) -> bool:
    """True when the reworded sentence names exactly the identifiers and numbers of its template."""
    return bool(reworded.strip()) and facts(template) == facts(reworded)


def _post_json(url: str, payload: dict, headers: Mapping[str, str] | None = None) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT,
                 **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed URLs)
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # say what the service answered (never the request, which carries the key), so the note explains the fallback
        detail = exc.read(300).decode("utf-8", "replace").strip()
        raise RewriteFailed(f"HTTP {exc.code} from {url}" + (f": {detail}" if detail else "")) from exc


def _sentences_from(content: str, expected: int) -> list[str]:
    try:
        sentences = json.loads(content)["sentences"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RewriteFailed(f"the model did not answer with the expected JSON: {exc}") from exc
    if not isinstance(sentences, list) or len(sentences) != expected or not all(isinstance(s, str) for s in sentences):
        raise RewriteFailed(f"the model returned {len(sentences) if isinstance(sentences, list) else 'no'} sentences, "
                            f"expected {expected}")
    return sentences


def _messages(sentences: Sequence[str]) -> list[dict]:
    return [{"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": json.dumps({"sentences": list(sentences)})}]


@dataclass(frozen=True)
class LocalRewriter:
    """A model served on this machine by Ollama: nothing leaves the machine."""

    model: str
    url: str = DEFAULT_LOCAL_URL

    @property
    def name(self) -> str:
        return f"local:{self.model}"

    def rewrite(self, sentences: Sequence[str]) -> list[str]:
        answer = _post_json(f"{self.url.rstrip('/')}/api/chat",
                            {"model": self.model, "messages": _messages(sentences), "stream": False, "format": "json"})
        return _sentences_from((answer.get("message") or {}).get("content", ""), len(sentences))


@dataclass(frozen=True)
class HostedRewriter:
    """The free hosted fallback (an OpenAI-compatible API such as Groq). The key is read from the environment."""

    api_key: str
    model: str = DEFAULT_HOSTED_MODEL
    url: str = HOSTED_URL

    @property
    def name(self) -> str:
        return f"hosted:{self.model}"

    def rewrite(self, sentences: Sequence[str]) -> list[str]:
        answer = _post_json(
            self.url,
            {"model": self.model, "messages": _messages(sentences), "temperature": 0,
             "response_format": {"type": "json_object"}},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            content = answer["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RewriteFailed(f"unexpected answer from {self.url}") from exc
        return _sentences_from(content, len(sentences))


def rewriters_from_env(env: Mapping[str, str] | None = None) -> list[Rewriter]:
    """The configured models, local first; empty when none is configured (templates only)."""
    env = os.environ if env is None else env
    found: list[Rewriter] = []
    if env.get("AMRTRACE_COPILOT_LOCAL_MODEL"):
        found.append(LocalRewriter(env["AMRTRACE_COPILOT_LOCAL_MODEL"],
                                   env.get("AMRTRACE_COPILOT_LOCAL_URL") or DEFAULT_LOCAL_URL))
    if env.get("GROQ_API_KEY"):
        found.append(HostedRewriter(env["GROQ_API_KEY"], env.get("AMRTRACE_COPILOT_HOSTED_MODEL") or DEFAULT_HOSTED_MODEL))
    return found


def reword(summary: CopilotSummary, rewriters: Sequence[Rewriter]) -> CopilotSummary:
    """The summary reworded by the first model that answers; any sentence that loses or adds a fact stays a template."""
    templates = [s.template_text for s in summary.sentences]
    notes = list(summary.notes)
    for rewriter in rewriters:
        try:
            answers = rewriter.rewrite(templates)
            if len(answers) != len(templates):
                raise RewriteFailed(f"{len(answers)} sentences for {len(templates)}")
        except Exception as exc:  # any failure of an optional layer falls back to the next one, then to templates
            notes.append(f"{rewriter.name} was not used: {type(exc).__name__}: {exc}")
            continue
        sentences = []
        kept = 0
        for sentence, answer in zip(summary.sentences, answers):
            if keeps_facts(sentence.template_text, answer):
                sentences.append(Sentence(answer.strip(), sentence.sources, sentence.template_text))
                kept += 1
            else:
                sentences.append(sentence)
        notes.append(f"{rewriter.name} reworded {kept} of {len(templates)} sentences; the rest are templates")
        return replace(summary, sentences=tuple(sentences), generator=rewriter.name, notes=tuple(notes))
    return replace(summary, notes=tuple(notes))
