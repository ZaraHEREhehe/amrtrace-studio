# Independent expected cases (task I-22, decision D-10)

These fixtures were written from the requirement texts and domain reasoning before any selector or evaluator output on
them was seen. Each file says where its expected result comes from (`derivation`). They are kept apart from the main
oracle folder because they are run by `tests/oracle/test_independent_cases.py`, which can register a change through
the change service (`apply_change`, where A-20 checks declared entities against derived ones) and checks the A-15
support annotations in a separate test from case selection.

| File | For | What it checks |
| ---- | --- | -------------- |
| `a20_omitted_entity.yaml` | A-20 | A declared change that leaves out entities its versions show: the omitted rules' cases are still found, or the change is refused naming them |
| `a20_same_id_pair_edit.yaml` | A-20 | A mapping rule keeps its id but links a new antibiotic: the case newly covered by the new pair is found, or the edit is refused |
| `a15_alternative_support.yaml` | A-15 / T39 | Expected effects for alternative support: one of two lost, both lost, one of two calls of a member lost, an edit, a single support |
| `a15_composite_support.yaml` | A-15 / T39 | Expected effects for composite support: half of a combination lost, a need-2 group broken, a need-2 group with a spare |
| `a15_contradiction.yaml` | A-15 / T39 | Expected effects for a conflict of AST results: a row corrected, a row removed, a corrected row with no conflict |

Rules: an expected set or effect is never changed to fit the code. A fixture that fails because the code disagrees
gets a `pending` entry naming the task that must resolve it, in a separate commit, so history shows the order.
