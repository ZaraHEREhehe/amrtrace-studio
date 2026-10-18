# stores one interpretation table from its YAML file, so a change event that names its rules can be registered
import argparse

import psycopg

from amrtrace.ingest.materialize_baseline import _conninfo
from amrtrace.interpretation.db import TableAlreadyStored, store_table
from amrtrace.interpretation.loader import InvalidTable, load_table


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Store an interpretation table and register a version node per rule.")
    parser.add_argument("--table", required=True, help="path to the table's YAML file")
    arguments = parser.parse_args(argv)
    try:
        table = load_table(arguments.table)
        with psycopg.connect(_conninfo()) as conn:
            count = store_table(conn, table)
            conn.commit()
    except TableAlreadyStored as problem:
        # storing twice changes nothing, so it is reported but not treated as a failure
        print(f"already stored: {problem}")
        return 0
    except (InvalidTable, OSError, psycopg.Error) as problem:
        print(f"STOP: {type(problem).__name__}: {problem}")
        return 1
    print(f"stored {table.interpretation_version}: {count} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
