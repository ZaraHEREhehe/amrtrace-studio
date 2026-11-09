# Research contribution: data categorisation and link discovery (G-09, OD-9)

Written by Aabia for the panel comment logged as OD-9: show the research contribution of AMRTrace through data
categorisation and link discovery. It also answers the doubts raised when the idea was first pitched: "it is just
classification", "it is just matching two files" and "it is a simple dependency graph". Every number below comes
from the real cohort (41,858 isolate and drug cases, *E. coli*, five drugs) and is reproducible from the repository;
the source of each is named.

## 1. The claim in one paragraph

Classifying a case once is easy. The hard part is that the inputs keep moving: NCBI corrects AST results, NCBI
re-runs AMRFinderPlus with new databases, and CLSI publishes new breakpoint editions. AMRTrace contributes two things
that make a classification stay correct as its inputs move. **Categorisation** turns each case, each piece of
evidence and each change into a small set of typed categories that can be compared across releases. **Link
discovery** records, for every case, exactly which evidence and rules it depends on, including rules and rows that
do not exist yet, so a change finds its cases without re-running everything. Together they let the system answer
"which conclusions does this change invalidate?" exactly, and prove the answer against an exhaustive recomputation.

## 2. Data categorisation

### 2.1 What is categorised

| Object | Categories | Why it matters |
|---|---|---|
| Case state | concordant resistant, concordant susceptible, discordant (genotype positive, phenotype S), discordant (phenotype R, no mapped genotype), unresolved | The unit that is compared across releases; a change is meaningful only if it moves a case between these |
| Phenotype label | the lab's label, or the label the breakpoint table gives, with a flag saying which was used (D-21, D-22) | Separates "the lab said" from "the standard says", so a re-interpretation never silently overrules a lab |
| Evidence | AST row, detailed genotype row, summary genotype row, each with a stable key | Lets the same row be recognised in two snapshots even when its id changes |
| Change | seven typed change events (interpretation version, mapping added, mapping retired, AST corrected, genotype changed, rule policy revised, evaluator version) | Each type has its own differ, so a change is described by the entities it touches, not by a free-text note |
| Review priority | newly discordant, state changed, label changed, re-verified (A-14) | Orders what a reviewer looks at first after a release |

### 2.2 What the categories revealed in real data

- **Lab labels the breakpoints cannot explain (D-21).** Reading every MIC against CLSI M100 Ed32 would change 1,541
  cases. 1,523 of them were submitted as `NOT_DEFINED` with a MIC, mostly by US veterinary laboratories, because
  M100 is a human standard. Categorising the label source, rather than overwriting it, turned this into a decision
  (keep any label the labs' edition cannot explain) instead of a silent error
  (`docs/design/interpretation_baseline_dry_run.md`).
- **Host matters for the standard (D-22).** About 22% of the cohort's cases come from animal isolates. Categorising
  hosts into groups let the same table apply CLSI VET01S rows to animals and M100 rows to humans
  (`docs/design/d22_host_breakpoints.md`).
- **Discordance is partly a data-quality category, not only a biological one.** Between the frozen snapshot (August
  2026) and a fresh pull (V2, 9 November 2026), NCBI itself corrected 1,046 AST phenotypes in 137 isolates.
  Re-evaluated under the release in force, 630 cases change state, and 596 of them (95%) move from discordant to
  concordant: 357 to concordant resistant and 239 to concordant susceptible. A release built once would keep
  reporting those cases as unexplained discordance (`docs/design/change_detection.md`, first real comparison).
- **Not every new edition is a change.** CLSI M100 Ed34, Ed35 and Ed36 were published after Ed33. Categorising each
  rule by its breakpoints, not by its edition, showed that none of them moves a breakpoint for the five panel drugs:
  the Ed36 table is the same as the Ed33 table, so zero cases are re-evaluated (A-18).

## 3. Link discovery

### 3.1 What is linked

Every evaluation writes the links it used: about 1.2 million dependency rows per release (1,237,992 in interpretation mode), from each case to the evidence it
read, the rules that decided it, the rules it looked for and did not find, and the versions it ran under, plus
344,526 rule-space rows (`docs/design/graph_design.md`). The links are discovered by evaluating, not declared by
hand, so they are exactly as wide as the evaluation was.

### 3.2 Links that matching two files would miss

- **Links to things that do not exist yet.** A new mapping rule or breakpoint rule has no edges, because no case
  could have used it. The graph records which (determinant, drug) pairs and rule keys each case looked for, so a
  rule introduced later still finds its cases (scenario C7; VET01S introduced 5,556 cases this way).
- **Links to rows that are not stored yet.** A new AST result or genotype row is linked to its isolate and drug, so
  its cases are found the moment the row exists (A-12).
- **Links across snapshots whose ids all changed.** The V1 curation puts the snapshot id inside AST and summary ids,
  so in V2 every one of those rows has a new id. Matching by id would report all of them removed and re-added.
  Linking by stable keys reported exactly the 1,046 corrected rows and the 6 re-run isolates, and nothing else.
- **Links through rules whose content did not change.** After a partial release, older edges carry an older table
  version. An edge also counts when its version gave the rule the same breakpoints (D-22), so carried cases are not
  missed by the next change.

### 3.3 What the links buy

The same CLSI Ed32 to Ed33 change, selected at four granularities on the real cohort (`docs/design/ablation.md`):

| Unit | Cases re-evaluated | Precision |
|---|---:|---:|
| Rule and changed MIC region (AMRTrace) | 116 | 96.6% |
| Rule, no region | 5,705 | 2.0% |
| Whole table | 39,323 | 0.3% |
| Whole snapshot (re-run everything) | 41,858 | 0.3% |

Recall is 100% at every level, checked against an independent oracle and an exhaustive recomputation. The fine links
re-evaluate about 360 times fewer cases than re-running everything, without missing one.

## 4. Why this is a research contribution, not preprocessing

- **The question is incremental, not one-off.** The contribution is keeping many derived conclusions correct as
  their inputs change, which is the problem studied for build systems and incremental computation (Mokhov,
  Mitchell and Peyton Jones, "Build Systems à la Carte", 2018), applied to evidence-based biological conclusions
  whose inputs are versioned, partly licensed and corrected by their sources.
- **The difficulty is in the links, not the classification.** A dependency that does not exist yet (a new rule), a
  row whose id changes with every snapshot, and a rule whose edition changes but whose content does not are each
  invisible to a file comparison. Each needed its own mechanism, and each was found by running real data.
- **Every result is checked.** Selective re-evaluation is compared with exhaustive recomputation before a release is
  published; the oracle is written by a different team member; and all real numbers above are reproducible from
  the scripts named.

## 5. Limits

- One organism, five drugs and one standards body (CLSI). The categories and links are generic (the engine holds no
  drug, organism or standard names), but only this cohort has been measured.
- New evidence is detected and its cases selected, but re-evaluating with the new values needs the new snapshot's
  evidence loaded (proposed I-20); the 630 changed cases were computed by a read-only evaluation, not a release.
- New isolates are a new cohort, not a change, and are left out of later snapshots.
- No user study: the claim is about correctness and cost, not about reviewers' decisions.
