const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(
  ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText,
  filename,
);

const {ERA_OUTREACH_BLOCKED, outreachAllowed} = require('../lib/outreach-policy.ts');

test('explicit ERA-only firms are blocked from outreach', () => {
  assert.equal(outreachAllowed({is_registered:false,is_era_only:true}), false);
  assert.match(ERA_OUTREACH_BLOCKED, /ERA-only/);
});

test('registered and historical unknown classifications retain existing behavior', () => {
  assert.equal(outreachAllowed({is_registered:true,is_era_only:false}), true);
  assert.equal(outreachAllowed({is_registered:null,is_era_only:null}), true);
});

test('inconsistent explicit classifications fail closed', () => {
  assert.equal(outreachAllowed({is_registered:false,is_era_only:false}), false);
  assert.equal(outreachAllowed({is_registered:true,is_era_only:true}), false);
});
