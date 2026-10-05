# registry that lets versioned rule sets plug in without editing the engine
from collections.abc import Callable

# a policy takes the antibiotic and the joined items, and returns a state plus the items that decided it
GenotypePolicy = Callable[[str, tuple[dict, ...]], tuple[str, tuple[dict, ...]]]

_GENOTYPE_POLICIES: dict[str, GenotypePolicy] = {}


def register_genotype_policy(case_rule_version: str, policy: GenotypePolicy) -> None:
    existing = _GENOTYPE_POLICIES.get(case_rule_version)
    # registering the same function twice is harmless, a different one is a mistake
    if existing is not None and existing is not policy:
        raise ValueError(
            f"a different genotype policy is already registered for {case_rule_version}"
        )
    _GENOTYPE_POLICIES[case_rule_version] = policy


def get_genotype_policy(case_rule_version: str) -> GenotypePolicy:
    policy = _GENOTYPE_POLICIES.get(case_rule_version)
    if policy is None:
        raise LookupError(
            f"no genotype policy registered for case rule version {case_rule_version}"
        )
    return policy


def registered_case_rule_versions() -> tuple[str, ...]:
    return tuple(sorted(_GENOTYPE_POLICIES))
