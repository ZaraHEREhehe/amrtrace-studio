"""Interpretation layer (task I-06): tables of breakpoints loaded from data files, rule lookup, interval logic.

The evaluator receives matching rules as plain dicts (rules_as_dicts); the table differ in
amrtrace.changes.differs.interpretation turns two tables into changed entities.
"""

from .db import TableAlreadyStored, TableNotFound, list_table_versions, load_table_from_db, store_table
from .intervals import (
    Interval,
    categories_overlap,
    category_interval,
    differing_regions,
    label_at,
    measurement_interval,
    touched_categories,
)
from .loader import InvalidTable, load_table, parse_table
from .models import (
    LABELS,
    OPS,
    Category,
    InterpretationRule,
    InterpretationTable,
    find_rules,
    make_rule_key,
    rule_from_dict,
    rules_as_dicts,
)
