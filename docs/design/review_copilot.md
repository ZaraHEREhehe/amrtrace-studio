# Review Copilot and Ask AMRTrace (I-19, I-25, I-29, I-30, I-31, D-27)

The Review Copilot writes a plain-language summary of why a case changed, for the reviewer looking at its dossier.
It is **generated text**: it is labelled as generated, kept in its own tables, and never evidence or an input to
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

## Where it goes (I-30)

- `GET /cases/{case_id}/copilot`: the trace and the narrative for the case's current comparison (or the one named by
  `before_release` / `after_release`). Every response carries `generated: true` and the label "Generated by the Review
  Copilot from stored records. It is not evidence and is never used to assign a state."
- **Cache keyed by inputs.** The text is kept in `copilot_cache` (migration 0019) under a fingerprint: a SHA-256 of
  the case, its two ledger state ids, the stored records the trace cites, the comparison asked for, the template,
  narrative and prompt versions and the configured models. Ledger states never change, so the same fingerprint always
  means the same facts. The first view writes the text (and asks the model, if one is configured) and keeps it;
  every later view with the same inputs reads it (`cached: true`) and asks nothing. A new release, a new review, a
  new prompt or another model gives a new fingerprint and one new row. When a configured model fails, the code's
  narrative is shown but not kept (`stored: false`), so the next view tries the model again. The response names its
  `fingerprint` and when the text was written.
- Before I-30, every press of "Write and store a summary" asked the model again and appended a row to
  `copilot_summary` (0015), so the table grew with near-identical rows. That table and `copilot_chat_answer` (0016)
  stay as read-only history; nothing writes them any more.
- **Pins.** `POST /cases/{case_id}/copilot/pins` with `{"kind": "summary"}` (or `{"kind": "answer", "fingerprint"}`
  for a cached chat answer) keeps the text on the case: a signed-in Reviewer or Admin only, as writing a summary was
  (Z-18). The pin copies the text and records the fingerprint and who pinned it, in `copilot_pin`, append-only, so it
  stands alone after its cache row is pruned. `GET /cases/{case_id}/copilot/pins` lists them, newest first.
- The dossier card shows "Up to date for these records" with the time the text was written, a "Pin to case" button
  for reviewers and admins, and the pins under the card.
- `GET` now runs on a write connection, because a first view writes the cache. Only the two copilot tables are
  written; the ledger is not touched.

## Ask AMRTrace: a conversation (I-31)

`POST /copilot/ask` answers the latest question of a conversation (`copilot/assistant.py`). The body is
`{"question": "...", "history": [{"role": "user" | "assistant", "text": "..."}], "context": {"case_id"?, "change_id"?}}`.
The browser keeps the conversation and sends it with each question; the server stays stateless and reads only the
last 8 turns, each cut to 2,000 characters. The context is the page the question was asked from: the dossier or
dependency view of a case, or a change.

1. **Records are looked up first, on the server, read-only.** The case in view (the I-25 records: comparison, change,
   versions, evidence, rules, labels, review), any case or change named in the question or the last four turns, the
   change that produced the case's state with its reach (cases re-evaluated and moved per published release, and the
   moves by state), and any determinant symbol in the question that the genotype rows hold. Each record has an id,
   the text the model may use, and the workbench page that shows it (`link`: dossier, dependencies, changes, exports
   or review-queue).
2. **One model call.** The configured model (D-27 order, local then hosted) gets the instructions, the recent turns as
   chat messages, and the question with the numbered records, and answers in JSON with record ids per sentence. The
   model is not given tools to call: the lookups above happen before it is asked, so there is one request per
   question (Groq's free tier limits requests per minute) and small local models without tool calling work too.
3. **Every sentence is checked** as I-29 checks narrative lines: it must cite records that were looked up, name no
   identifier or number they do not hold, and say nothing that decides, recommends or treats. A sentence that fails
   is dropped and counted in the notes. If nothing survives, or there is no model, code answers from the records on
   the question's topic: a change's reach for "is it the only one?" questions, the determinant record, or the I-25
   case answer.
4. **Blocks** are drawn by code from the same records: the case's transition (before and after state), a change's
   moves as a small table, and a determinant card. A block is returned only when a kept sentence cites its records.

The response holds `answer`, `sources` (with `link`), `blocks`, `suggestions` (follow-up questions), `mode`,
`generator`, `notes`, the generated label, and `fingerprint`. The answer is cached in `copilot_cache` (kind `answer`)
under a fingerprint of the question, the recent turns, the context, the looked-up records and blocks, the prompt
version and the models, so the same question in the same conversation is not sent to the model twice; cached answers
are pruned 7 days after their last use. A model failure is answered by code and not kept. A Reviewer or Admin pins an
answer about a case with `POST /cases/{case_id}/copilot/pins` and `{"kind": "answer", "fingerprint": "..."}`.
Asking needs no sign-in and writes nothing but that cache.

The I-25 routes below stay for the contract agreed with I-24; the workbench uses `/copilot/ask` from I-32 on.

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
  (`tests/integration/test_copilot_chat.py`). Since I-30 the same test caches and pins false claims and hides both
  `copilot_cache` and `copilot_pin`.
- Every sentence's sources are checked to exist in the database, and the templates are checked with the network
  switched off (same file).

## Limits

- The templates explain what changed in the stored records, not the biology behind it.
- A language model's wording is checked for identifiers, numbers and state-assigning words only; a composed sentence
  could still change the emphasis of the trace, which is why the trace and its records are always one click away.
