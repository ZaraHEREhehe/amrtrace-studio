"""Real Chromium UI checks with synthetic I-18 responses only.

All HTTP requests stay on the temporary localhost static server. Every /api/
request is intercepted and served from in-memory fixtures, so this runner
cannot create review records in any deployed or local PostgreSQL database.
"""
from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

WEB = Path(__file__).resolve().parents[1]
ARTIFACTS = Path("artifacts/z17-browser")
ARTIFACTS.mkdir(parents=True, exist_ok=True)

CASES = [
    {
        "case_id": "CASE_Z17_A",
        "target_acc": "PDT-QA-1",
        "antibiotic": "gentamicin",
        "state_id": 1101,
        "release_id": "R2",
        "state_code": "UNRESOLVED",
        "labels_changed": 2,
    },
    {
        "case_id": "CASE_Z17_B",
        "target_acc": "PDT-QA-2",
        "antibiotic": "meropenem",
        "state_id": 1102,
        "release_id": "R2",
        "state_code": "CONCORDANT_RESISTANT",
        "labels_changed": 1,
    },
]
reviews = {}
writes = []
page_errors = []


class QuietFiles(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        pass


def respond(route):
    request = route.request
    parsed = urlparse(request.url)
    path = parsed.path
    method = request.method
    query = parse_qs(parsed.query)
    if path == "/api/review-queue" and method == "GET":
        items = [
            item for item in CASES if item["case_id"] not in reviews
            and (not query.get("drug") or item["antibiotic"] == query["drug"][0])
            and (not query.get("state") or item["state_code"] == query["state"][0])
        ]
        offset = int(query.get("offset", ["0"])[0])
        limit = int(query.get("limit", ["25"])[0])
        route.fulfill(status=200, json={
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "items": items[offset:offset + limit],
        })
        return
    if path == "/api/summary" and method == "GET":
        route.fulfill(status=200, json={
            "total_cases": 2,
            "cases_with_state": 2,
            "state_counts": [],
            "drugs": [
                {"antibiotic": "gentamicin", "total": 1, "unresolved": 1, "discordant": 0},
                {"antibiotic": "meropenem", "total": 1, "unresolved": 0, "discordant": 0},
            ],
            "latest_release": None,
            "labels_changed_cases": 2,
        })
        return
    if path == "/api/changes/types" and method == "GET":
        route.fulfill(status=200, json=[])
        return
    if path.startswith("/api/cases/") and path.endswith("/review-status") and method == "GET":
        case_id = path.split("/")[3]
        item = next((i for i in CASES if i["case_id"] == case_id), None)
        if item is None:
            route.fulfill(status=404, json={"error_code": "case_not_found", "message": "Not found"})
            return
        action = reviews.get(case_id, {}).get("action")
        status = {"CONFIRM": "CONFIRMED", "CORRECT": "CORRECTED", "MARK_UNRESOLVED": "MARKED_UNRESOLVED"}.get(action, "UNVERIFIED")
        route.fulfill(status=200, json={
            "case_id": case_id,
            "review_status": status,
            "unverified": status == "UNVERIFIED",
            "state_id": item["state_id"],
            "release_id": item["release_id"],
            "state_code": item["state_code"],
            "labels_changed": item["labels_changed"],
            "latest_review_id": 500 if action else None,
            "latest_review_action": action,
        })
        return
    if path.startswith("/api/cases/") and path.endswith("/review") and method == "POST":
        case_id = path.split("/")[3]
        item = next((i for i in CASES if i["case_id"] == case_id), None)
        data = request.post_data_json
        if item is None or data.get("state_id") != item["state_id"]:
            route.fulfill(status=409, json={"error_code": "review_not_allowed", "message": "Stale published state"})
            return
        writes.append((case_id, data))
        reviews[case_id] = data
        route.fulfill(status=201, json={
            "review_id": 500 + len(writes),
            "state_id": item["state_id"],
            "case_id": case_id,
            "reviewer": data["reviewer"],
            "action": data["action"],
            "reason": data["reason"],
            "corrected_state_code": data.get("corrected_state_code"),
            "created_at": "2026-11-09T00:00:00Z",
        })
        return
    if method != "GET":
        raise AssertionError("Unexpected HTTP write: " + method + " " + path)
    route.fulfill(status=404, json={"message": "No synthetic route for " + path})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietFiles)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_port)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1365, "height": 900})
            page = context.new_page()
            page.route("**/api/**", respond)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(url + "/index.html#/review-queue", wait_until="domcontentloaded")
            expect(page.locator('section[data-view="review-queue"]')).to_be_visible()
            expect(page.locator("#review-queue-results tbody tr")).to_have_count(2, timeout=12000)
            assert "2" in page.locator("#review-queue-pager").inner_text()
            print("PASS: Review Queue lists two unverified states and total")

            page.locator("#review-queue-drug").select_option("gentamicin")
            page.locator('#review-queue-filters button[type="submit"]').click()
            expect(page.locator("#review-queue-results tbody tr")).to_have_count(1)
            assert page.locator("#review-queue-results").inner_text().count("PDT-QA-1") == 1
            print("PASS: Drug filtering and shareable route")

            page.locator("#review-queue-drug").select_option("")
            page.locator("#review-queue-state").select_option("CONCORDANT_RESISTANT")
            page.locator('#review-queue-filters button[type="submit"]').click()
            expect(page.locator("#review-queue-results tbody tr")).to_have_count(1)
            assert "PDT-QA-2" in page.locator("#review-queue-results").inner_text()
            print("PASS: State filtering")

            page.locator("#review-queue-state").select_option("")
            page.locator('#review-queue-filters button[type="submit"]').click()
            expect(page.locator("#review-queue-results tbody tr")).to_have_count(2)
            page.locator('button[aria-label="Review CASE_Z17_A"]').click()
            expect(page.locator("#review-queue-detail-card")).to_be_visible()
            expect(page.locator("#review-queue-submit")).to_be_enabled()
            page.locator("#review-queue-reviewer").fill("qa-reviewer")
            page.locator("#review-queue-reason").fill("Synthetic confirmation")
            page.locator("#review-queue-review-form button[type=submit]").click()
            expect(page.locator("#review-queue-results tbody tr")).to_have_count(1)
            assert len(writes) == 1 and writes[0][1]["state_id"] == 1101
            assert writes[0][1]["action"] == "CONFIRM"
            print("PASS: Confirm submits append-only review with exact state_id and reloads queue")

            page.locator('button[aria-label="Review CASE_Z17_B"]').click()
            expect(page.locator("#review-queue-detail-card")).to_be_visible()
            page.locator("#review-queue-action").select_option("CORRECT")
            expect(page.locator("#review-queue-corrected-state")).to_be_enabled()
            page.locator("#review-queue-reviewer").fill("qa-reviewer")
            page.locator("#review-queue-reason").fill("Synthetic correction")
            page.locator("#review-queue-corrected-state").select_option("UNRESOLVED")
            page.locator('#review-queue-review-form button[type="submit"]').click()
            expect(page.locator("#review-queue-results")).to_contain_text(
                "No unverified cases match these filters."
            )
            assert len(writes) == 2 and writes[1][1]["state_id"] == 1102
            assert writes[1][1]["corrected_state_code"] == "UNRESOLVED"
            print("PASS: Correct requires corrected state and removes case after append")

            page.screenshot(path=str(ARTIFACTS / "review-queue.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator('section[data-view="review-queue"]')).to_be_visible()
            page.screenshot(path=str(ARTIFACTS / "review-queue-mobile.png"), full_page=True)
            assert not page_errors, page_errors
            print("PASS: Mobile viewport; no browser execution errors; no real API writes")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
