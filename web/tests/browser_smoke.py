"""Browser-only QA against the checked-out frontend and synthetic API replies.

Everything is served on 127.0.0.1. API writes are intercepted by Playwright
and rejected with a known 422; no database or deployment is contacted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("artifacts/browser-qa")
OUTPUT.mkdir(parents=True, exist_ok=True)
TYPES = [
    "INTERPRETATION_VERSION",
    "MAPPING_ADDED",
    "MAPPING_RETIRED",
    "AST_CORRECTED",
    "GENOTYPE_CHANGED",
    "RULE_POLICY_REVISED",
    "EVALUATOR_VERSION",
]
NODE_TYPES = {
    "MAPPING_ADDED": "mapping_rule",
    "MAPPING_RETIRED": "mapping_rule",
    "AST_CORRECTED": "ast_evidence",
    "GENOTYPE_CHANGED": "genotype_evidence",
    "RULE_POLICY_REVISED": "policy_rule",
    "EVALUATOR_VERSION": "case_rule_version",
}
SNAPSHOT = b'{"release_id":"REL-QA-02","case_states":[]}\n'
DIGEST = hashlib.sha256(SNAPSHOT).hexdigest()
submissions = []
unexpected_writes = []
page_errors = []


class QuietStatic(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietStatic)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = "http://127.0.0.1:" + str(server.server_port)

    def intercepted_api(route):
        request = route.request
        parsed = urlparse(request.url)
        path, method = parsed.path, request.method
        params = parse_qs(parsed.query)
        if method == "POST" and path == "/api/changes":
            submitted = request.post_data_json
            submissions.append(submitted)
            if submitted["type"] == "INTERPRETATION_VERSION":
                problem = "old_version TABLE_V1 is not a registered version"
            else:
                problem = (
                    "changed_entities[0]: new_version 'V2' of "
                    "genotype_evidence/GENO-X is not a registered version"
                )
            route.fulfill(
                status=422,
                json={
                    "error_code": "invalid_change_event",
                    "message": "Change event validation failed",
                    "details": {"problems": [problem]},
                },
            )
            return
        if method != "GET":
            unexpected_writes.append([method, path])
            route.fulfill(status=405, json={"error": "blocked in QA"})
            return
        if path == "/api/changes/types":
            route.fulfill(
                status=200,
                json=[
                    {
                        "type": name,
                        "has_differ": name != "EVALUATOR_VERSION",
                        "can_derive_entities": name == "INTERPRETATION_VERSION",
                    }
                    for name in TYPES
                ],
            )
        elif path == "/api/changes":
            route.fulfill(status=200, json=[])
        elif path == "/api/summary":
            route.fulfill(
                status=200,
                json={
                    "latest_release": {
                        "release_id": "REL-QA-02",
                        "source_snapshot_id": "QA-SNAPSHOT",
                        "interpretation_version": "TABLE_V2",
                    },
                    "total_cases": 0,
                    "cases_with_state": 0,
                    "drugs": [],
                    "state_counts": [],
                    "labels_changed_cases": 0,
                },
            )
        elif path == "/api/runs":
            route.fulfill(status=200, json=[])
        elif path == "/api/releases":
            route.fulfill(
                status=200,
                json=[
                    {"release_id": "REL-QA-01", "release_seq": 1},
                    {"release_id": "REL-QA-02", "release_seq": 2},
                ],
            )
        elif path == "/api/export":
            assert params.get("as_of_release") == ["REL-QA-02"], params
            if params.get("format") == ["sha256"]:
                route.fulfill(
                    status=200,
                    body=DIGEST + "\n",
                    content_type="text/plain",
                )
            elif params.get("format") == ["json"]:
                route.fulfill(
                    status=200,
                    body=SNAPSHOT,
                    content_type="application/json",
                    headers={"X-AMRTrace-Snapshot-SHA256": DIGEST},
                )
            else:
                route.fulfill(status=400, json={"message": "Unsupported format"})
        else:
            route.fulfill(status=404, json={"message": "No test stub for " + path})

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox"],
            )
            context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.route("**/api/**", intercepted_api)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(base_url + "/#/changes", wait_until="domcontentloaded")
            page.wait_for_function(
                "document.querySelectorAll('#change-type option').length === 8",
                timeout=15000,
            )
            page.locator("#toggle-change-form").click()
            expect(page.locator("#change-form-card")).to_be_visible()
            option_values = page.locator("#change-type option").evaluate_all(
                "(els) => els.map(el => el.value).filter(Boolean)"
            )
            assert option_values == TYPES, (option_values, TYPES)
            print("PASS: all seven registered options loaded from API")

            page.locator("#change-id").fill("CHG-QA-001")
            page.locator("#old-version").fill("V1")
            page.locator("#new-version").fill("V2")
            page.locator("#initiator").fill("isolated-browser-qa")

            for kind in TYPES:
                page.locator("#change-type").select_option(kind)
                checkbox = page.locator("#change-derive")
                rows = page.locator(".change-entity-row")
                if kind == "INTERPRETATION_VERSION":
                    assert checkbox.is_checked() and checkbox.is_enabled()
                    assert page.locator("#change-entities-section").is_hidden()
                    checkbox.uncheck()
                    expect(rows).to_have_count(1)
                    checkbox.check()
                    assert page.locator("#change-entities-section").is_hidden()
                else:
                    assert not checkbox.is_checked() and checkbox.is_disabled()
                    expect(rows).to_have_count(1)
                    first = rows.first
                    first.locator('[data-entity-field="node_id"]').fill(
                        "POLICY|VALUE" if kind == "RULE_POLICY_REVISED" else "GENO-X"
                    )
                    kind_input = first.locator('[data-entity-field="node_type"]')
                    assert kind_input.input_value() in ("", NODE_TYPES[kind])
                    if kind == "EVALUATOR_VERSION":
                        kind_input.fill(NODE_TYPES[kind])
                    page.locator("#change-add-entity").click()
                    expect(rows).to_have_count(2)
                    rows.nth(1).get_by_role("button", name="Remove entity").click()
                    expect(rows).to_have_count(1)

                before = len(submissions)
                page.locator('#change-form button[type="submit"]').click()
                page.wait_for_function(
                    "(n) => document.querySelector('#change-form-errors').hidden === false",
                    arg=before,
                    timeout=10000,
                )
                assert len(submissions) == before + 1, (kind, len(submissions))
                body = submissions[-1]
                assert body["type"] == kind, body
                assert body["declared_scope"] == {}, body
                assert body["change_id"] == "CHG-QA-001", body
                if kind == "INTERPRETATION_VERSION":
                    assert body["changed_entities"] == [], body
                else:
                    assert len(body["changed_entities"]) == 1, body
                    entity = body["changed_entities"][0]
                    assert entity["node_type"] == NODE_TYPES[kind], body
                    if kind == "MAPPING_ADDED":
                        assert entity["old_version"] is None, body
                    if kind == "MAPPING_RETIRED":
                        assert entity["new_version"] is None, body
                if kind == "GENOTYPE_CHANGED":
                    assert "not a registered version" in page.locator(
                        "#change-form-errors"
                    ).inner_text()
                    attr = rows.first.locator(
                        '[data-entity-field="new_version"]'
                    ).get_attribute("aria-invalid")
                    assert attr == "true", attr
                    assert "not a registered version" in rows.first.inner_text()
                    assert page.locator("#change-id").input_value() == "CHG-QA-001"
            page.screenshot(path=str(OUTPUT / "z16-changes.png"), full_page=True)
            print("PASS: seven UI form submissions intercepted; exact payloads and 422 feedback checked")

            page.locator('[data-nav="exports"]').click()
            expect(page.locator('section[data-view="exports"]')).to_be_visible()
            expect(page.locator("#exports-release")).to_have_value("REL-QA-02")
            expect(page.locator("#exports-hash")).to_have_text(DIGEST, timeout=15000)
            expect(page.locator("#exports-download-json")).to_be_enabled()
            expect(page.locator("#exports-download-hash")).to_be_enabled()
            with TemporaryDirectory() as tmp:
                with page.expect_download(timeout=15000) as d:
                    page.locator("#exports-download-json").click()
                download = d.value
                assert download.suggested_filename == "amrtrace-REL-QA-02.json"
                output_file = Path(tmp) / download.suggested_filename
                download.save_as(output_file)
                assert output_file.read_bytes() == SNAPSHOT
                expect(page.locator("#exports-hash-status")).to_contain_text("SHA-256 verified")
                with page.expect_download(timeout=15000) as d:
                    page.locator("#exports-download-hash").click()
                digest_download = d.value
                assert digest_download.suggested_filename == "amrtrace-REL-QA-02.sha256"
                digest_file = Path(tmp) / digest_download.suggested_filename
                digest_download.save_as(digest_file)
                assert digest_file.read_text() == DIGEST + "\n"
            page.screenshot(path=str(OUTPUT / "z21-exports.png"), full_page=True)
            print("PASS: Z-21 release selection, SHA-256 and byte-identical downloads")

            # Check narrow-screen accessibility without writing any event.
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator('[data-nav="changes"]').click()
            assert page.locator("#toggle-change-form").count() == 1
            print("PASS: changes page reachable at mobile viewport")

            assert not unexpected_writes, unexpected_writes
            assert not page_errors, page_errors
            assert len(submissions) == len(TYPES), submissions
            print("PASS: no unmocked API mutation, no browser page errors")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
