// Optional read-only integration check against the configured serving database.
const assert = require("node:assert/strict");
const { loadEnvConfig } = require("@next/env");
const fs = require('node:fs');
const ts = require('typescript');
const Module = require('node:module');
// Next supplies this compile-time marker. The standalone test runs only on Node.
const originalLoad = Module._load;
Module._load = function(name, ...args) { return name === 'server-only' ? {} : originalLoad.call(this, name, ...args); };
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText, filename);

async function main() {
  loadEnvConfig(process.cwd());
  const { targetData, firmData } = require("../lib/queries.ts");
  const { pool, db } = require("../lib/db.ts");
  const client = await pool.connect();
  await client.query('BEGIN READ ONLY');
  const readDb = require('drizzle-orm/node-postgres').drizzle(client);
  db.execute = readDb.execute.bind(readDb);
  try {
    const first = await targetData({page:1});
    const second = await targetData({page:2});
    assert.ok(first.rows.length > 0);
    assert.equal(new Set([...first.rows,...second.rows].map(row=>row.firm_id)).size,first.rows.length+second.rows.length);
    for(const row of first.rows) {
      assert.equal(row.dataset_version,first.rows[0].dataset_version);
      for(const key of ['succession_status','custodian_status','ownership_status','part2a_status','office_contact_status','phone_available']) assert.notEqual(row[key],undefined);
    }
    for(const sortField of ['score','aum','accounts','employees']) {
      const ascending=await targetData({sortField,sortOrder:'asc',priority:'PRIORITY_A'});
      assert.ok(ascending.rows.every(row=>row.priority_category==='PRIORITY_A'));
    }
    const empty=await targetData({search:'SCM_NONEXISTENT_TEST_7e6c5'});
    assert.equal(empty.total,0); assert.deepEqual(empty.rows,[]);
    const detail=await firmData(String(first.rows[0].firm_id));
    assert.equal(detail.firm.dataset_version,first.rows[0].dataset_version);
    for(const group of ['advCustodians','advScheduleObservations']) assert.ok(detail[group].every(row=>row.dataset_version===detail.firm.dataset_version));
    console.log(JSON.stringify({status:'PASS',dataset:first.rows[0].dataset_version,total:first.total,checks:['pagination uniqueness','filters','four sorts','empty search','ADV indicators','firm detail dataset alignment']}));
  } finally { await client.query('ROLLBACK'); client.release(); await pool.end(); }
}
main().catch(error=>{console.error('Read-only smoke failed:',error.code || error.name, error.cause?.code, error.cause?.message || error.message);process.exitCode=1;});
