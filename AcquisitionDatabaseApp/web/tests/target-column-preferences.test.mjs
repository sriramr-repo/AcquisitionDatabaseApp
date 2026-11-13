import test from "node:test";
import assert from "node:assert/strict";
import { sanitizeTargetColumnPreferences, targetColumnKeys } from "../lib/target-column-preferences.ts";

test("accepts a complete reordered column set and removes duplicates", () => {
  const result = sanitizeTargetColumnPreferences({ order: [...targetColumnKeys].reverse().concat("firm"), hidden: ["aum", "aum"] });
  assert.deepEqual(result.order, [...targetColumnKeys].reverse());
  assert.deepEqual(result.hidden, ["aum"]);
});

test("rejects incomplete column orders", () => {
  assert.equal(sanitizeTargetColumnPreferences({ order: ["firm"], hidden: [] }), null);
});

test("the firm column cannot be hidden and unknown keys are discarded", () => {
  const result = sanitizeTargetColumnPreferences({ order: targetColumnKeys, hidden: ["firm", "unknown", "priority"] });
  assert.deepEqual(result.hidden, ["priority"]);
});
