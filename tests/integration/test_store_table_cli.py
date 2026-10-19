# the small command that stores a table before a change event can name its rules
import pathlib

import pytest

from amrtrace.ingest import store_table as cli
from amrtrace.interpretation import list_table_versions

pytestmark = pytest.mark.integration
TABLE = pathlib.Path(__file__).resolve().parents[2] / "data" / "interpretation" / "clsi_m100_ed32_vet01s_ed7.yaml"


def test_the_command_stores_a_table_once_and_accepts_a_second_run(scratch_database_url, monkeypatch, capsys):
    from psycopg.conninfo import conninfo_to_dict

    parts = conninfo_to_dict(scratch_database_url)
    for name, key in (("HOST", "host"), ("PORT", "port"), ("USER", "user"), ("PASSWORD", "password"), ("DBNAME", "dbname")):
        monkeypatch.setenv(f"AMRTRACE_PG_{name}", str(parts.get(key, "")))
    assert cli.main(["--table", str(TABLE)]) == 0
    assert "23 rules" in capsys.readouterr().out
    assert cli.main(["--table", str(TABLE)]) == 0
    assert "already stored" in capsys.readouterr().out
    import psycopg
    with psycopg.connect(scratch_database_url) as conn:
        assert "CLSI_M100_ED32_VET01S_ED7" in list_table_versions(conn)
