const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.tsx'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,filename);
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const Evidence = require('../app/components/RepresentativeEvidence.tsx').default;
test('partial representative renders unavailable without crashing',()=>{
 const html=renderToStaticMarkup(React.createElement(Evidence,{representative:{}}));
 assert.match(html,/Unavailable/);
 assert.doesNotMatch(html,/undefined|null/);
});
test('source evidence and conflicts remain visible and escaped',()=>{
 const html=renderToStaticMarkup(React.createElement(Evidence,{representative:{source_url:'https://adviserinfo.sec.gov/individual/summary/123',effective_fields:{phone:'0',business_address:'<script>bad</script>',stale:true},conflicts:{employer:{monthly:'1',live:'2'}}}}));
 assert.match(html,/Refresh needed/);
 assert.match(html,/Conflicting evidence/);
 assert.match(html,/noopener/);
 assert.doesNotMatch(html,/<script>/);
});
test('review rationale and separate monthly status date remain visible',()=>{
 const html=renderToStaticMarkup(React.createElement(Evidence,{representative:{effective_fields:{registration_date:'2026-08-12',provenance:{registration_date:{source_type:'monthly_feed'}},review_decisions:[{review_id:'r',resolution:'monthly_preferred',reviewer:'operator',reviewed_at:'2026-09-14',rationale:'Different registration concepts'}]}}}));
 assert.match(html,/Registration status date \(monthly\)/);
 assert.match(html,/Resolved evidence reviews/);
 assert.match(html,/Different registration concepts/);
 assert.match(html,/operator/);
});
