"""G-09 read-only HTTP contract tests with a deterministic miniature ledger.

Runs against the real FastAPI application and new transition endpoints, using a
local SQLite adapter rather than connecting to any research/production DB.
"""
from __future__ import annotations

import re
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import amrtrace.api.transitions as transitions_api
from amrtrace.api.db import get_connection
from amrtrace.api.main import app
from amrtrace.ledger.errors import ReleaseNotFound

CR = 'CONCORDANT_RESISTANT'
CS = 'CONCORDANT_SUSCEPTIBLE'
GP = 'DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S'
U = 'UNRESOLVED'


@pytest.fixture
def client(monkeypatch):
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE release (release_id TEXT, release_seq INTEGER, status TEXT);
        CREATE TABLE "case" (case_id TEXT, target_acc TEXT, antibiotic TEXT);
        CREATE TABLE case_state (state_id INTEGER, case_id TEXT, release_id TEXT, state_code TEXT);
    ''')
    conn.executemany('INSERT INTO release VALUES (?,?,?)', [
        ('R1',1,'PUBLISHED'),('R2',2,'PUBLISHED'),('RX',3,'BLOCKED'),
        ('R3',4,'PUBLISHED'),('R4',5,'PUBLISHED')])
    conn.executemany('INSERT INTO "case" VALUES (?,?,?)', [
        ('A','ISOLATE_A','gentamicin'),('B','ISOLATE_B','gentamicin'),
        ('C','ISOLATE_C','ceftriaxone'),('D','ISOLATE_D','ciprofloxacin')])
    conn.executemany('INSERT INTO case_state VALUES (?,?,?,?)', [
        (1,'A','R1',CR),(2,'B','R1',GP),(3,'C','R1',CS),(4,'D','R1',U),
        (5,'A','R2',CS),(6,'B','RX',CR),(7,'B','R3',CR),(8,'C','R4',GP)])

    class Cursor:
        def __init__(self):self.inner=None
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def execute(self,sql,params):
            # Translate only psycopg's named placeholders. The query logic is unchanged.
            sql = re.sub(r'%\((\w+)\)s', r':\1', sql)
            self.inner = conn.execute(sql,params)
        def fetchall(self):return [dict(x) for x in self.inner.fetchall()]

    class Connection:
        def cursor(self,**kwargs):return Cursor()

    def get_release_fake(_,release_id):
        row=conn.execute('SELECT * FROM release WHERE release_id=?',(release_id,)).fetchone()
        if row is None:raise ReleaseNotFound(release_id)
        return SimpleNamespace(release_id=release_id,release_seq=row['release_seq'],
            status=row['status'],version_vector={'interpretation_version':'TEST'},
            verification_level='SELECTIVE')

    monkeypatch.setattr(transitions_api,'get_release',get_release_fake)
    app.dependency_overrides[get_connection]=lambda:Connection()
    try:
        with TestClient(app) as api:
            yield api
    finally:
        app.dependency_overrides.pop(get_connection,None)
        conn.close()


def test_effective_published_release_transitions(client):
    result=client.get('/releases/transitions',params={'before':'R2','after':'R4'})
    assert result.status_code==200, result.text
    data=result.json()
    assert data['comparable_cases']==4
    assert data['missing_before']==data['missing_after']==0
    flows={(f['before_state'],f['after_state']):f['count'] for f in data['flows']}
    assert flows[(CS,CS)]==1  # R2 update carried across to R4
    assert flows[(GP,CR)]==1  # R3 update carried across to R4
    assert flows[(CS,GP)]==1  # R4 change
    assert flows[(U,U)]==1   # untouched case remains unresolved


def test_filter_matches_drill_down(client):
    data=client.get('/releases/transitions',params={
        'before':'R2','after':'R4','antibiotic':'gentamicin'}).json()
    assert data['comparable_cases']==2
    page=client.get('/releases/transitions/cases',params={
        'before':'R2','after':'R4','antibiotic':'gentamicin',
        'from_state':GP,'to_state':CR,'limit':25,'offset':0})
    assert page.status_code==200,page.text
    assert [item['case_id'] for item in page.json()['items']]==['B']


def test_blocked_release_and_invalid_state_are_rejected(client):
    assert client.get('/releases/transitions?before=RX&after=R4').status_code==409
    assert client.get('/releases/transitions?before=R4&after=R2').status_code==422
    assert client.get('/releases/transitions/cases',params={
        'before':'R2','after':'R4','from_state':'INTERMEDIATE','to_state':CR}).status_code==422
