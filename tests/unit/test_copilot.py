# Review Copilot (I-19): the language-model layer may only reword, and no engine package can read the copilot

import ast
import io
import urllib.error
from pathlib import Path

import pytest

from amrtrace.copilot import CopilotSummary, HostedRewriter, LocalRewriter, Sentence, SourceRef, keeps_facts, reword
from amrtrace.copilot import language_model, rewriters_from_env
from amrtrace.copilot.templates import verbatim, words

SRC = Path(__file__).resolve().parents[2] / "src" / "amrtrace"
STATE = SourceRef("case_state", "41")
CHANGE = SourceRef("change_event", "CHG-1")


def summary(*texts):
    return CopilotSummary("CASE_1", 40, 41, "STATE_CHANGED", tuple(Sentence(t, (STATE, CHANGE)) for t in texts))


class Fixed:
    def __init__(self, answers, name="fake"):
        self.answers, self.name = answers, name

    def rewrite(self, sentences):
        return list(self.answers)


class Broken:
    name = "broken"

    def rewrite(self, sentences):
        raise OSError("no network")


def test_codes_read_as_words_and_versions_stay_verbatim():
    assert words("DISCORDANT_PHENOTYPE_R") == "discordant phenotype r"
    assert words("phenotype_state") == "phenotype state"
    assert words(None) == "none"
    assert verbatim("CLSI_M100_ED33") == "CLSI_M100_ED33"
    assert verbatim(["C1", "C2"]) == "C1, C2"


def test_a_sentence_without_a_stored_record_is_refused():
    with pytest.raises(ValueError, match="at least one stored record"):
        Sentence("Something happened.", ())


def test_a_dependency_source_must_name_its_release_and_node_type():
    with pytest.raises(ValueError, match="release_id"):
        SourceRef("dependency", "rule-1")
    with pytest.raises(ValueError, match="unknown source kind"):
        SourceRef("copilot_summary", "1")
    ref = SourceRef("dependency", "rule-1", release_id="R3", node_type="interpretation_rule")
    assert SourceRef.from_dict(ref.as_dict()) == ref


def test_a_rewording_must_keep_every_identifier_and_number():
    template = "Release R3 changed this case after change CHG-1 moved the MIC 8 rule."
    assert keeps_facts(template, "After change CHG-1 moved the MIC 8 rule, release R3 changed this case.")
    assert not keeps_facts(template, "Release R3 changed this case after change CHG-1.")          # lost a number
    assert not keeps_facts(template, "Release R4 changed this case after change CHG-1, MIC 8.")   # new id
    assert not keeps_facts(template, "  ")


def test_a_model_rewords_only_the_sentences_that_keep_their_facts():
    original = summary("Release R3 changed this case.", "It now reads AST result A1.")
    result = reword(original, [Fixed(["In release R3 this case changed.", "It now reads AST result A2."])])
    assert result.generator == "fake"
    assert [s.text for s in result.sentences] == ["In release R3 this case changed.", "It now reads AST result A1."]
    # a reworded sentence keeps its template and its sources
    assert result.sentences[0].template_text == "Release R3 changed this case."
    assert all(s.sources == (STATE, CHANGE) for s in result.sentences)
    assert "fake reworded 1 of 2 sentences" in result.notes[-1]


def test_a_failing_model_falls_back_to_the_next_one_then_to_templates():
    original = summary("Release R3 changed this case.")
    assert reword(original, [Broken(), Fixed(["Release R3 changed it."], "second")]).generator == "second"
    fallback = reword(original, [Broken(), Fixed(["one", "two"], "wrong count")])
    assert fallback.generator == "templates"
    assert [s.text for s in fallback.sentences] == ["Release R3 changed this case."]
    assert len(fallback.notes) == 2


def test_models_are_configured_from_the_environment_local_first():
    assert rewriters_from_env({}) == []
    found = rewriters_from_env({"GROQ_API_KEY": "k", "AMRTRACE_COPILOT_LOCAL_MODEL": "llama3.2"})
    assert [r.name for r in found] == ["local:llama3.2", "hosted:openai/gpt-oss-20b"]
    chosen = rewriters_from_env({"GROQ_API_KEY": "k", "AMRTRACE_COPILOT_HOSTED_MODEL": "qwen/qwen3.8-27b"})
    assert [r.name for r in chosen] == ["hosted:qwen/qwen3.8-27b"]


def test_both_model_clients_read_the_sentences_from_their_answers(monkeypatch):
    calls = []

    def fake_post(url, payload, headers=None):
        calls.append((url, headers))
        content = '{"sentences": ["Release R3 changed it."]}'
        if "api/chat" in url:
            return {"message": {"content": content}}
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(language_model, "_post_json", fake_post)
    assert LocalRewriter("m").rewrite(["x"]) == ["Release R3 changed it."]
    assert HostedRewriter("secret").rewrite(["x"]) == ["Release R3 changed it."]
    assert calls[1][1] == {"Authorization": "Bearer secret"}
    with pytest.raises(language_model.RewriteFailed):
        LocalRewriter("m").rewrite(["x", "y"])


def test_requests_name_the_client_and_an_http_refusal_explains_itself(monkeypatch):
    """Groq answers 403 to Python's default user agent; the request names AMRTrace, and a refusal is reported."""
    seen = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        seen.append(request)
        return Answer(b'{"choices": [{"message": {"content": "{\\"sentences\\": [\\"ok\\"]}"}}]}')

    monkeypatch.setattr(language_model.urllib.request, "urlopen", fake_urlopen)
    assert HostedRewriter("secret").rewrite(["x"]) == ["ok"]
    assert seen[0].get_header("User-agent") == language_model.USER_AGENT
    assert seen[0].get_header("Authorization") == "Bearer secret"

    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"error code: 1010"))

    monkeypatch.setattr(language_model.urllib.request, "urlopen", refuse)
    result = reword(summary("Release R3 changed this case."), [HostedRewriter("secret")])
    assert result.generator == "templates"
    assert "HTTP 403" in result.notes[-1] and "error code: 1010" in result.notes[-1]
    assert "secret" not in result.notes[-1]


# ---------- rule 9: generated text is never an input to state assignment ----------

ENGINE_PACKAGES = ("evaluator", "deps", "ledger", "changes", "reeval", "ingest", "interpretation", "policies",
                   "triage", "monitor")


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_engine_package_imports_the_copilot_or_reads_its_table():
    offenders = []
    for package in ENGINE_PACKAGES:
        for path in sorted((SRC / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if any(name.startswith("amrtrace.copilot") for name in _imports(path)) or "copilot" in text.lower():
                offenders.append(str(path.relative_to(SRC)))
    assert offenders == []


def test_only_the_copilot_routes_use_the_copilot_in_the_api():
    users = sorted(p.name for p in (SRC / "api").glob("*.py")
                   if any(n.startswith("amrtrace.copilot") or n == "copilot" for n in _imports(p))
                   or "from .copilot import" in p.read_text(encoding="utf-8"))
    assert users == ["copilot.py", "main.py"]
