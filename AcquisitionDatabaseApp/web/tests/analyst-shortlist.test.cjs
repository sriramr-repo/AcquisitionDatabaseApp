const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");

require.extensions[".ts"] = (module, filename) => module._compile(
  ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText,
  filename,
);

const { parseShortlistAddRequest, shortlistRequestMatchesActiveDataset } = require("../lib/analyst-shortlist.ts");

test("shortlist additions require a non-empty dataset version", () => {
  assert.equal(parseShortlistAddRequest(null), null);
  assert.equal(parseShortlistAddRequest({ datasetVersion: "  " }), null);
  assert.equal(parseShortlistAddRequest({ datasetVersion: 20261107 }), null);
  assert.deepEqual(parseShortlistAddRequest({ datasetVersion: "  ia07012026  " }), { datasetVersion: "ia07012026" });
});

test("stale Target Explorer rows cannot add to the active shortlist", () => {
  const request = parseShortlistAddRequest({ datasetVersion: "ia07012026" });
  assert.equal(shortlistRequestMatchesActiveDataset(request, "ia07012026"), true);
  assert.equal(shortlistRequestMatchesActiveDataset(request, "ia08012026"), false);
});
