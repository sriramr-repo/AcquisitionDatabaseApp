// Optional read-only integration check against a migrated serving database.
const assert = require("node:assert/strict");
const { loadEnvConfig } = require("@next/env");
const fs = require("node:fs");
const ts = require("typescript");
const Module = require("node:module");
const originalLoad = Module._load;
Module._load = function(name, ...args) { return name === "server-only" ? {} : originalLoad.call(this, name, ...args); };
require.extensions[".ts"] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, "utf8"), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText, filename);

async function main() {
  loadEnvConfig(process.cwd());
  const { iapdChangesData } = require("../lib/queries.ts");
  const { pool, db } = require("../lib/db.ts");
  const client = await pool.connect();
  await client.query("BEGIN READ ONLY");
  const readDb = require("drizzle-orm/node-postgres").drizzle(client);
  db.execute = readDb.execute.bind(readDb);
  try {
    const first = await iapdChangesData({page:1});
    const second = await iapdChangesData({page:2});
    assert.ok(first.comparison);
    assert.ok(first.rows.length > 0);
    assert.equal(new Set([...first.rows,...second.rows].map(row=>`${row.comparison_id}:${row.firm_id}`)).size,first.rows.length+second.rows.length);
    for (const type of ["new_representatives","representative_no_longer_present","employer_changes","registration_changes","disclosure_changes","material_contact_changes"]) {
      const filtered = await iapdChangesData({changeType:type,page:1});
      assert.ok(filtered.total >= filtered.rows.length);
    }
    const under = await iapdChangesData({aum:"under200",page:1});
    assert.ok(under.rows.every(row=>Number(row.total_aum)<200000000));
    const state = first.rows.find(row=>row.organization_state)?.organization_state;
    if (state) {
      const filtered = await iapdChangesData({state:String(state),page:1});
      assert.ok(filtered.rows.every(row=>String(row.organization_state).toUpperCase()===String(state).toUpperCase()));
    }
    console.log(JSON.stringify({status:"PASS",comparison:first.comparison.comparison_id,total:first.total}));
  } finally { await client.query("ROLLBACK"); client.release(); await pool.end(); }
}
main().catch(error=>{console.error("IAPD Changes smoke failed:",error.code||error.name,error.cause?.message||error.message);process.exitCode=1;});
