// I-29: the narrative on top of the trace, the grouped trace and where each cited record opens
import assert from "node:assert/strict";
import test from "node:test";

import { citation, copilotNarrative, narrativeByline, sourceLink, traceGroups } from "../copilot.mjs";

const summary = {
  case_id: "CASE 1",
  generator: "hosted:openai/gpt-oss-20b",
  sentences: [
    { text: "Release R8 changed this case.", group: "outcome", sources: [{ kind: "case_state", id: "41" }] },
    { text: "Change CHG-1 produced it.", group: "cause", sources: [{ kind: "change_event", id: "CHG-1" }] },
    {
      text: "It now depends on rule-1.",
      group: "rules",
      sources: [{ kind: "dependency", id: "rule-1", release_id: "R8", node_type: "interpretation_rule" }],
    },
    { text: "It now depends on rule-2.", group: "rules", sources: [{ kind: "dependency", id: "rule-2", release_id: "R8", node_type: "x" }] },
    { text: "Nobody has reviewed it.", group: "review", sources: [{ kind: "case_state", id: "41" }] },
  ],
  narrative: {
    headline: { text: "R8 moved this case because of CHG-1.", cites: [1, 2] },
    story: [{ text: "Change CHG-1 swapped the rule.", cites: [2, 3] }],
    checks: [{ text: "Two releases moved at once.", cites: [1] }],
    followups: ["Which other cases did CHG-1 change?"],
    generator: "hosted:openai/gpt-oss-20b",
  },
};

test("the narrative is shown as written, with its citations", () => {
  const narrative = copilotNarrative(summary);
  assert.equal(narrative.headline.text, "R8 moved this case because of CHG-1.");
  assert.deepEqual(narrative.story[0].cites, [2, 3]);
  assert.equal(narrative.checks.length, 1);
  assert.deepEqual(narrative.followups, ["Which other cases did CHG-1 change?"]);
});

test("a summary stored before the narrative existed shows its first sentence as the headline", () => {
  const old = { ...summary, narrative: null };
  assert.deepEqual(copilotNarrative(old).headline, { text: "Release R8 changed this case.", cites: [1] });
  assert.equal(copilotNarrative({ sentences: [] }), null);
});

test("the trace is grouped in order and keeps each sentence's number", () => {
  const groups = traceGroups(summary);
  assert.deepEqual(groups.map((g) => g.label), ["Outcome", "Cause", "Rules", "Review"]);
  assert.deepEqual(groups[2].rows.map((r) => r.number), [3, 4]);
  assert.equal(groups[2].rows[0].sources[0], "dependency record rule-1 (R8)");
});

test("each cited record opens the page that shows it", () => {
  assert.deepEqual(sourceLink({ kind: "change_event", id: "CHG-1" }, "CASE 1"), { href: "#/changes/CHG-1", text: "Open change" });
  assert.equal(sourceLink({ kind: "dependency", id: "x" }, "CASE 1").href, "#/dependencies/CASE%201");
  assert.equal(sourceLink({ kind: "case_state", id: "41" }, "CASE 1").href, "#/dossier/CASE%201");
  assert.equal(sourceLink({ kind: "release", id: "R8" }, "CASE 1").href, "#/exports/R8");
  assert.equal(sourceLink({ kind: "case_state", id: "41" }, "CASE 1", "review").href, "#/review-queue");
  assert.equal(citation(summary, 2).link.href, "#/changes/CHG-1");
  assert.equal(citation(summary, 9), null);
});

test("the byline says who wrote the narrative in plain words", () => {
  assert.equal(narrativeByline("templates"), "Written by code from the stored records.");
  assert.equal(narrativeByline("hosted:openai/gpt-oss-20b"),
    "Written by openai/gpt-oss-20b from the stored records, and checked against them.");
});
