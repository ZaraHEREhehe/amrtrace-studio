# Specifications

Frozen specification documents copied from the legacy pipeline repository. They are stored byte for byte and must not be edited.

| File | Original name | Rule ID | sha256 |
|---|---|---|---|
| `CASE_RULES_V1.md` | `docs/cases/M8_2_CASE_RULES_V1.md` | `CASE_RULES_V1` | `c4338fc4c50fdadb2c62a92c7bf3c8c3100d467b2d3aaa7a9a00c8ba573406f2` |

The file was renamed on import so that its name matches the rule ID stored in the `case_rule_version` column. The contents are unchanged, which the hash confirms. The original implementation was `scripts/build_case_states_v1.py` in the legacy repository.

To verify on Windows:

```powershell
(Get-FileHash docs\spec\CASE_RULES_V1.md -Algorithm SHA256).Hash.ToLower()
```
