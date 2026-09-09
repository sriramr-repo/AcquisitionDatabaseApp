const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
// Compile only in memory; tests never load database configuration or external services.
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) => {
  module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText, filename);
};
const {advIndicators,custodianStatus,evidenceStatus,officeLines,officeStatus,yesNo} = require('../lib/adv-visibility.ts');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const AdvDetails = require('../app/components/AdvDetails.tsx').default;
const Indicators = require('../app/components/AdvIndicators.tsx').default;

test('succession is strictly tri-state, independent of analyst readiness', () => {
  assert.equal(yesNo(false),'No'); assert.equal(yesNo(null),'Unknown'); assert.equal(yesNo('false'),'Unknown');
  assert.equal(advIndicators({succession_indicator:false,succession_readiness_assessment:'Ready'}).succession_status,'No');
});
test('custodian review takes precedence over accepted rows and non-applicability', () => {
  assert.equal(custodianStatus(null,[]),'Unavailable');
  assert.equal(custodianStatus(false,[]),'Not required');
  assert.equal(custodianStatus(true,[{review_status:'ACCEPTED'}]),'Reported');
  assert.equal(custodianStatus(false,[{review_status:'ACCEPTED'}]),'Review');
  assert.equal(custodianStatus(true,[{review_status:'ACCEPTED'},{review_status:'PROPOSED'}]),'Review');
  assert.equal(custodianStatus(true,[{review_status:'REJECTED'}]),'Unavailable');
});
test('brochure and ownership coverage never accepts proposals or hides conflicts', () => {
  assert.equal(evidenceStatus([{review_status:'CONFLICTING'},{review_status:'ACCEPTED'}]),'Review');
  assert.equal(advIndicators({has_principals:true}).ownership_status,'Available');
  assert.equal(advIndicators({has_principals:true,schedule_observations:[{field_key:'adv.ownership_control',review_status:'PROPOSED'}]}).ownership_status,'Review');
  assert.equal(advIndicators({schedule_observations:[{field_key:'adv.brochure_intelligence',review_status:'ACCEPTED'}]}).part2a_status,'Available');
  assert.equal(advIndicators({}).part2a_status,'Unavailable');
});
test('addresses preserve leading zero postal codes and international regions may be absent', () => {
  const office={main_office_street_address_1:' 1 Main St ',main_office_street_address_2:'Suite 2',main_office_city:'Boston',main_office_state:'MA',main_office_country:'United States',main_office_postal_code:'02110',main_office_phone:'  '};
  assert.deepEqual(officeLines(office),['1 Main St','Suite 2','Boston, MA 02110','United States']);
  assert.equal(officeStatus(office),'Complete');
  assert.equal(officeStatus({...office,main_office_postal_code:null}),'Partial');
  assert.equal(officeStatus({}),'Unavailable');
  assert.equal(officeStatus({main_office_street_address_1:'1 Road',main_office_city:'Singapore',main_office_country:'Singapore'}),'Complete');
  assert.equal(advIndicators(office).phone_available,false);
});
test('firm detail displays all custodian fields, evidence values, unknowns, dates and review state', () => {
  const html=renderToStaticMarkup(React.createElement(AdvDetails,{data:{firm:{dataset_version:'current'},facts:{},advFacts:{succession_indicator:false},advFiling:{},sources:[],research:{},iapdPrincipals:[],advCustodians:[{custodian_id:'c1',legal_name:'Test custodian',primary_business_name:'Trading name',related_person:false,broker_dealer_sec_number:'8-123',legal_entity_identifier:'LEI123',sma_aum:0,review_status:'PROPOSED',confidence:'HIGH',source_page:12,source_hash:'hash',created_at:new Date('2026-09-01T00:00:00Z')}],advScheduleObservations:[{observation_id:'o1',field_key:'adv.disclosure_details',form_item:'11',value_json:{reported:false,count:0},source_url:'https://example.com/filing',review_status:'CONFLICTING',source_hash:'hash'}]}}));
  for(const text of ['Trading name','8-123','LEI123','$0','PROPOSED','CONFLICTING','2026-09-01','Unavailable','reported','false','count']) assert.ok(html.includes(text),text);
  assert.ok(html.includes('target="_blank"'));
  assert.ok(!html.includes('[object Object]'));
});
test('indicators link within the same tab to six explicit sections', () => {
  const html=renderToStaticMarkup(React.createElement(Indicators,{row:{firm_id:'123',...advIndicators({})}}));
  for(const anchor of ['succession','custodians','ownership','brochure','main-office']) assert.ok(html.includes(`/firms/123#${anchor}`));
  assert.ok(!html.includes('target="_blank"'));
});
