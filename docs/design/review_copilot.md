# Review Copilot (I-19, D-27)

The Review Copilot writes a plain-language summary of why a case changed, for the reviewer looking at its dossier.
It is **generated text**: it is labelled as generated, kept in its own table, and never evidence or an input to
state assignment (rule 9).

## What it reads

Only stored records, all of which the dossier already shows:

| Record | Used for |
| --- | --- |
| The before/after comparison (I-13, `reeval/diff.py`) | the outcome, the state-field changes, the version changes, the dependency records added and removed |
| `change_event` | which change produced the new state, its type, versions and who registered it |
| `ast_evidence`, `genotype_evidence` | the label, MIC, standard and snapshot of each AST result, the determinant and database of each genotype row |
| The new state's explanation | label flags: which rule read a measurement differently from the lab's label |
| Review status (I-18, D-28) | whether the state waits for a reviewer |

## How it writes

1. **Templates first** (`copilot/templates.py`, version `COPILOT_TEMPLATES_V1`). Each sentence is built from one kind
   of record and names those records (`SourceRef`: a state, release, change, dependency record, evidence row or
   review). A sentence without a source cannot be built. At most three records of one kind are named one by one; the
   rest are counted in one sentence that still lists them as sources. The same records always give the same
   sentences, and no network is used.
2. **An optional language model only rewords** (`copilot/language_model.py`). It gets the template sentences and must
   return the same number in the same order. A reworded sentence keeps its template's sources, and it is kept only if
   it carries exactly the identifiers and numbers of its template; otherwise the template sentence is shown. If no
   model answers, the templates stand. Order: a local model served by Ollama (`AMRTRACE_COPILOT_LOCAL_MODEL`), then
   the free hosted fallback (`GROQ_API_KEY`, model `openai/gpt-oss-20b` unless `AMRTRACE_COPILOT_HOSTED_MODEL` names
   another; Groq retires models, so the name is a setting). Keys live in `.env`, never in the repository. Each
   summary's notes (in the API response and the stored row) say which model was used or why it was not.

## The narrative on top of the trace (I-29)

Reviewers found the list of template sentences hard to read: it repeated the page in bullets. Since I-29 the
template sentences are the **trace**, grouped by what they are about (outcome, cause, versions, evidence, rules, lab
results, review; `COPILOT_TEMPLATES_V2` adds the group, the sentences are unchanged), and a short **narrative** sits on
top of them (`copilot/narrative.py`, `COPILOT_NARRATIVE_V1`):

| Part | What it is | Written by |
| --- | --- | --- |
| Headline | one sentence: what happened to the case and why | code, or a model |
| Story | two to five plain sentences: the cause, what it means for the lab result, where the review stands | code, or a model |
| Checks ("worth a look") | a change that says it replaced a different version than the one the case was read with; rules and evidence moving in the same release; a lab result a rule no longer reads as S, I or R; a trace cut short | code only |
| Follow-ups | questions the chat can answer next | code only |

Every line cites the trace sentences it rests on by number. Version codes read as editions
(`CLSI_M100_ED36_VET01S_ED7_R1` reads "CLSI M100 ed. 36, VET01S ed. 7, R1"); the trace keeps the codes as stored.

**Compose, then verify.** The code always writes the narrative first, so the copilot works with no model and no
network. A configured model (D-27 order) may then write its own headline and story from the numbered trace and the
code's draft. Each line it writes is kept only if:

1. it cites trace sentences that exist;
2. every identifier and number in it appears in the sentences it cites (a subset, so the model may summarise; the
   parts of a code and its readable edition name count as present);
3. it says nothing that decides, recommends or treats (`should`, `recommend`, `reclassify`, `is actually`, `treat`,
   `prescribe`, `dose`, `clinically` and similar are refused);
4. it is at most 400 characters.

If the headline fails, or no story line survives, the code's narrative is used and the notes say why. Checks and
follow-ups never come from a model. This replaces the I-19 rule that a model may only reword sentence by sentence,
which is why the old output could only ever be the same bullets in other words.

The dossier card shows the headline, the story with numbered citation chips (each opens a small popover with the
sentence, its records and a link to the page that shows them), the checks in an amber box, the follow-up questions,
and "Show the full trace" with the grouped sentences and an "Open …" link per row (case dossier, change, dependency
view, release, review queue).

## Where it goes

- `GET /cases/{case_id}/copilot`: the newest stored summary for the case's current comparison, or fresh template
  sentences (`stored: false`). Every response carries `generated: true` and the label "Generated by the Review
  Copilot from stored records. It is not evidence and is never used to assign a state."
- `POST /cases/{case_id}/copilot` with `{"mode": "templates" | "language_model"}`: writes a summary and stores it in
  `copilot_summary` (migration 0015, append-only), with which two states it explains and what wrote it. Writing
  a summary needs a signed-in Reviewer or Admin (Z-18); reading one stays public, like every other `GET`.
- The dossier shows it in its own card, "Review Copilot (generated)", below Before / after, each sentence followed by
  the records it came from. It loads on its own, so a problem with it never hides the evidence panels.

## Chat: questions about one case (I-25)

`POST /cases/{case_id}/copilot/chat` with `{"question": "..."}` answers one question from the case's stored records
(`copilot/chat.py`). The response follows the contract agreed for I-24 and I-25:
`{"answer": [{"text", "source_ids"}], "sources": [{"id", "kind", "label"}], "generated": true, "mode": ...}`, plus
the generated label and notes. Asking writes nothing and needs no sign-in, like a `GET`.

- **Retrieval** reads only the selected case's records: the before/after comparison, its current dependency subgraph
  (A-10), the evidence rows that subgraph reads, the change that produced its state, and its review status. Each
  becomes one or more template sentences that name their records; a source id is `kind:id` (a dependency record is
  `dependency:<release>:<node type>:<node id>`).
- **`template`**: the question names a topic (why it changed, evidence, rules, versions, review, which change), and
  the sentences on that topic are the answer. A configured model may reword them under the I-19 rule: a sentence
  that loses or adds an identifier or number goes back to its template. The mode is then `local` or `hosted`.
- **`local` / `hosted`**: no topic matched and a model is configured (same order as D-27: Ollama, then Groq). The
  model gets the numbered records only and must cite them. A sentence is kept only if it cites records that exist
  and every identifier and number in it appears in those records; the rest are dropped and the notes say how many.
- **`records_only`**: no topic matched and no model answered. The answer is the retrieved records themselves.
- **Saving**: `POST /cases/{case_id}/copilot/chat/saved` (signed-in Reviewer or Admin, as for summaries) answers the
  question again on the server and stores that answer in `copilot_chat_answer` (migration 0016, append-only) with who
  saved it. Answer text sent by the browser is never stored.
- **In the dossier (I-24)**, the Review Copilot card has an "Ask about this case" box under the summary. Each answer
  sentence is followed by the records it cites, the generated caption is always shown with an answer (it does not
  depend on anything in the response), and one plain line says how the answer was written (from the stored records,
  reworded by a model, or no direct answer so the records are listed). "Save answer" is enabled only for a signed-in
  Reviewer or Admin, after an answer is shown.

## Why it can never become evidence

- No engine package (evaluator, deps, ledger, changes, reeval, ingest, interpretation, policies, triage, monitor)
  imports `amrtrace.copilot` or names its table; in the API only the copilot routes use it
  (`tests/unit/test_copilot.py`).
- The chain test stores summaries full of false claims, hides their table, and runs selection, selective
  re-evaluation, the exhaustive comparison and the release gate: it still passes, so no step read the table
  (`tests/integration/test_review_copilot.py`). The chat has the same test for saved answers and their table
  (`tests/integration/test_copilot_chat.py`).
- Every sentence's sources are checked to exist in the database, and the templates are checked with the network
  switched off (same file).

## Limits

- The templates explain what changed in the stored records, not the biology behind it.
- A language model's wording is checked for identifiers, numbers and state-assigning words only; a composed sentence
  could still change the emphasis of the trace, which is why the trace and its records are always one click away.
