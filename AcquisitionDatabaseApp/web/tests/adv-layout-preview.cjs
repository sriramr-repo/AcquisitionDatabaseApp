// Synthetic, local-only visual fixture. No database, authentication secret or live firm data is loaded.
const fs=require('node:fs');
const Module=require('node:module');
const ts=require('typescript');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
for(const extension of ['.ts','.tsx']) require.extensions[extension]=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,filename);
const rows=[
  {firm_id:'123',name:'Example Advisory Partners',succession_status:'No',custodian_status:'Review',ownership_status:'Available',part2a_status:'Unavailable',office_contact_status:'Complete',phone_available:true},
  {firm_id:'456',name:'Example International Wealth Management',succession_status:'Unknown',custodian_status:'Unavailable',ownership_status:'Unavailable',part2a_status:'Review',office_contact_status:'Partial',phone_available:false},
].map(row=>({...row,dataset_version:'fixture',organization_state:'MA',priority_category:'PRIORITY_A',acquisition_score:93.5,total_aum:42000000,discretionary_aum:42000000,individual_hnw_share:0.98,total_account_count:150,employee_count:3,research_status:'NOT_STARTED',seller_intent_status:'UNKNOWN',outreach_status:'NOT_RESEARCHED'}));
const originalLoad=Module._load;
Module._load=function(name,...args){if(name==='../../lib/queries') return {targetData:async()=>({rows,total:2,page:1,pageSize:25})};return originalLoad.call(this,name,...args);};
const Targets=require('../app/targets/page.tsx').default;
const Details=require('../app/components/AdvDetails.tsx').default;
const data={firm:{dataset_version:'fixture'},facts:{main_office_street_address_1:'1 Example Street',main_office_street_address_2:'Suite 200',main_office_city:'Boston',main_office_state:'MA',main_office_country:'United States',main_office_postal_code:'02110',main_office_phone:'+1 617 555 0100'},advFacts:{succession_indicator:false},advFiling:{filing_date:'2026-08-03'},sources:[],iapdPrincipals:[],advCustodians:[],advScheduleObservations:[]};
require('node:http').createServer(async(req,res)=>{
  const component=req.url.startsWith('/firms/')?React.createElement(Details,{data}):await Targets({searchParams:Promise.resolve({})});
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+fs.readFileSync('app/globals.css','utf8')+'</style><div class="shell"><aside class="nav">Synthetic visual fixture</aside><main class="main">'+renderToStaticMarkup(component)+'</main></div>');
}).listen(3102,'127.0.0.1',()=>console.log('Synthetic ADV preview: http://127.0.0.1:3102/targets'));
