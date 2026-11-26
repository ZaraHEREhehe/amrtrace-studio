"""G-09 SQL semantics regression using an independent SQLite miniature ledger.

This is NOT a replacement for PostgreSQL integration/CI. It exercises the same
windowed effective-state and FULL OUTER JOIN query on fixed known outcomes.
"""
from __future__ import annotations

import ast
import re
import sqlite3
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
SOURCE = HERE / "src/amrtrace/api/transitions.py"
SYNTAX = ast.parse(SOURCE.read_text())
ASSIGN = next(node for node in SYNTAX.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "PAIRED_STATES_SQL" for t in node.targets))
PAIRS_SQL = ast.literal_eval(ASSIGN.value)
# SQLite 3.40+ supports full joins; psycopg named placeholders are translated.
PAIRS_SQL = re.sub(r"%\((\w+)\)s", r":\1", PAIRS_SQL)

CR = "CONCORDANT_RESISTANT"
CS = "CONCORDANT_SUSCEPTIBLE"
GP = "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S"
PR = "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE"
U = "UNRESOLVED"


def mini_ledger():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
      CREATE TABLE release (release_id TEXT PRIMARY KEY, release_seq INTEGER, status TEXT);
      CREATE TABLE "case" (case_id TEXT PRIMARY KEY, target_acc TEXT, antibiotic TEXT);
      CREATE TABLE case_state (state_id INTEGER PRIMARY KEY, case_id TEXT, release_id TEXT, state_code TEXT);
    ''')
    conn.executemany('INSERT INTO release VALUES(?,?,?)', [
        ('R1',1,'PUBLISHED'),('R2',2,'PUBLISHED'),('RX',3,'BLOCKED'),
        ('R3',4,'PUBLISHED'),('R4',5,'PUBLISHED'),('RD',6,'DRAFT'),
    ])
    cases = [('A','ISO_A','gentamicin'),('B','ISO_B','gentamicin'),
             ('C','ISO_C','ceftriaxone'),('D','ISO_D','ciprofloxacin'),
             ('E','ISO_E','meropenem'),('F','ISO_F','gentamicin')]
    conn.executemany('INSERT INTO "case" VALUES(?,?,?)', cases)
    states = [(1,'A','R1',CR),(2,'B','R1',GP),(3,'C','R1',CS),
              (4,'D','R1',U),(5,'E','R1',PR),
              (6,'A','R2',CS),  # new interpretation at R2
              (7,'B','RX',CR),  # blocked release must be ignored
              (8,'B','R3',CR),  # new interpretation at R3
              (9,'C','R4',GP),  # R4 touches only C and F
              (10,'F','R4',CS), # newly introduced case lacks prior state
              (11,'D','RD',CR)] # draft must never change D
    conn.executemany('INSERT INTO case_state VALUES(?,?,?,?)', states)
    return conn


def pairs(conn, before_seq=2, after_seq=5, antibiotic=None):
    return conn.execute(PAIRS_SQL + 'SELECT * FROM paired ORDER BY case_id',
                        dict(before_seq=before_seq,after_seq=after_seq,antibiotic=antibiotic)).fetchall()


class EffectiveTransitionSQL(unittest.TestCase):
    def setUp(self):
        self.conn = mini_ledger()
    def tearDown(self):
        self.conn.close()

    def test_selective_release_carries_forward_untouched_cases(self):
        rows = pairs(self.conn)
        self.assertEqual(len(rows), 6)
        observed = {x['case_id']:(x['before_state'],x['after_state']) for x in rows}
        self.assertEqual(observed['A'],(CS,CS))
        self.assertEqual(observed['B'],(GP,CR))
        self.assertEqual(observed['C'],(CS,GP))
        self.assertEqual(observed['D'],(U,U))
        self.assertEqual(observed['E'],(PR,PR))
        self.assertEqual(observed['F'],(None,CS))

    def test_blocked_and_draft_states_are_excluded(self):
        observed = {r['case_id']:(r['before_state'],r['after_state']) for r in pairs(self.conn)}
        self.assertEqual(observed['D'], (U,U))
        self.assertEqual(observed['B'], (GP,CR))

    def test_filtered_cohort_is_exact(self):
        rows = pairs(self.conn,antibiotic='gentamicin')
        self.assertEqual([row['case_id'] for row in rows],['A','B','F'])

    def test_aggregate_and_drilldown_return_same_members(self):
        params = dict(before_seq=2,after_seq=5,antibiotic=None,from_state=GP,to_state=CR)
        group = self.conn.execute(PAIRS_SQL + '''SELECT before_state,after_state,count(*) n FROM paired
          WHERE before_state IS NOT NULL AND after_state IS NOT NULL
          GROUP BY before_state,after_state ORDER BY before_state,after_state''', params).fetchall()
        member = self.conn.execute(PAIRS_SQL + '''SELECT case_id FROM paired
          WHERE before_state=:from_state AND after_state=:to_state
          ORDER BY case_id LIMIT 26 OFFSET 0''', params).fetchall()
        self.assertEqual(len(member), 1)
        self.assertEqual(member[0]['case_id'], 'B')
        self.assertEqual(sum(r['n'] for r in group),5)
        self.assertEqual(sum(r['n'] for r in group if r['before_state']!=r['after_state']),2)

    def test_same_edition_compare_no_transition(self):
        rows = pairs(self.conn,before_seq=1,after_seq=1)
        self.assertEqual(len(rows),5)
        self.assertTrue(all(row['before_state']==row['after_state'] for row in rows))


if __name__ == '__main__':
    unittest.main()
