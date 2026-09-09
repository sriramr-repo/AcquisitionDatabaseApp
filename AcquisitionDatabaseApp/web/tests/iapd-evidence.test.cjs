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
