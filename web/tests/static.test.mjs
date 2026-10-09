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
    /COPY web\/ \/usr\/share\/nginx\/html\//,
  );
});
