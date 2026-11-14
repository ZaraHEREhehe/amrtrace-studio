import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


function read(path) {
  return readFileSync(
    new URL(path, import.meta.url),
    "utf8",
  );
}


const api = read("../api.mjs");
const app = read("../app.mjs");
const index = read("../index.html");
const nginx = read("../../docker/nginx.web.conf");
const dockerfile = read("../../docker/Dockerfile.web");


test("browser API traffic uses the same-origin /api proxy", () => {
  assert.match(
    api,
    /const API_ROOT = "\/api";/,
  );

  assert.doesNotMatch(
    `${api}\n${app}`,
    /https?:\/\/(?:localhost|127\.0\.0\.1)/,
  );
});


test("browser rendering does not inject API HTML", () => {
  assert.doesNotMatch(app, /\.innerHTML\s*=/);
  assert.doesNotMatch(app, /insertAdjacentHTML/);
});


test("application shell loads its stylesheet and module", () => {
  assert.match(
    index,
    /href="\/styles\.css"/,
  );

  assert.match(
    index,
    /type="module" src="\/app\.mjs"/,
  );
});


test("nginx proxies /api to the compose API service", () => {
  assert.match(
    nginx,
    /location \/api\//,
  );

  assert.match(
    nginx,
    /proxy_pass http:\/\/api:8000\//,
  );
  // Preserve the browser-facing port for the Z-18 Origin check.
  assert.match(nginx, /proxy_set_header Host \$http_host;/);

  assert.match(
    nginx,
    /try_files \$uri \$uri\/ \/index\.html;/,
  );
});


test("web image contains nginx config and application files", () => {
  assert.match(
    dockerfile,
    /COPY docker\/nginx\.web\.conf \/etc\/nginx\/conf\.d\/default\.conf/,
  );

  assert.match(
    dockerfile,
    /COPY --chown=nginx:nginx web\/ \/usr\/share\/nginx\/html\//,
  );
});

test("run page exposes the documented Z-09 controls", () => {
  assert.match(index, /data-nav="runs"/);
  assert.match(index, /id="reevaluation-form"/);
  assert.match(index, /id="run-lookup-form"/);
  assert.match(index, /id="equivalence-detail"/);

  assert.match(app, /startReevaluation/);
  assert.match(app, /getRunEquivalence/);
  assert.match(app, /decisionLabel/);
});

test("case dossier exposes the complete Z-11 workflow", () => {
  assert.match(index, /data-nav="dossier"/);
  assert.match(index, /id="dossier-form"/);
  assert.match(index, /id="dossier-overview"/);
  assert.match(index, /id="dossier-history"/);
  assert.match(index, /id="dossier-diff-form"/);
  assert.match(index, /id="dossier-graph"/);
  assert.match(index, /id="dossier-review-form"/);
  assert.match(index, /id="dossier-reviews"/);
  assert.match(index, /id="dossier-export"/);

  assert.match(app, /getCaseDiff/);
  assert.match(app, /createReview/);
  assert.match(app, /renderDossierDependencies/);
  assert.match(app, /routeHash\("exports", current\.release_id\)/);
});


test("dossier keeps API-derived values text-only", () => {
  assert.doesNotMatch(app, /\.innerHTML\s*=/);
  assert.doesNotMatch(app, /insertAdjacentHTML/);
  assert.match(app, /textContent/);
});


test("the shell has the prototype's dashboard and case explorer pages", () => {
  assert.match(index, /data-nav="dashboard"/);
  assert.match(index, /data-nav="explorer"/);
  assert.match(index, /id="dashboard-kpis"/);
  assert.match(index, /id="explorer-form"/);
  assert.match(index, /id="topbar-search"/);

  assert.match(app, /getSummary/);
  assert.match(app, /listCases/);
});


test("Z-17 review queue has filters, state-bound review actions, and a dossier link", () => {
  const html = read("../index.html");
  const js = read("../app.mjs");
  assert.match(html, /data-nav="review-queue"/);
  assert.match(html, /data-view="review-queue"/);
  for (const id of [
    "review-queue-filters", "review-queue-drug", "review-queue-state", "review-queue-sort",
    "review-queue-results", "review-queue-pager",
    "review-queue-review-form", "review-queue-action",
    "review-queue-reason", "review-queue-corrected-state",
    "review-queue-review-status",
  ]) {
    assert.ok(html.includes('id="' + id + '"'), "Missing " + id);
  }
  assert.match(js, /getCaseReviewStatus\(item\.case_id\)/);
  assert.match(js, /buildReviewPayload\(/);
  assert.match(js, /createReview\(target\.case_id, payload\)/);
  assert.match(js, /loadReviewQueue\(currentReviewQueueFilters, reviewQueueOffset\)/);
  assert.doesNotMatch(js, /\.innerHTML\s*=|insertAdjacentHTML\(/);
});

test("Z-17 displays the API's review status in Explorer and Dossier", () => {
  const js = read("../app.mjs");
  assert.match(js, /row\.review_status/);
  assert.match(js, /reviewBadge\(dossier\.review_status\)/);
  assert.match(js, /getCaseReviewStatus\(activeDossierCaseId\)/);
});
