import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const source=fs.readFileSync(path.join(process.cwd(),'public/assets/chart-engine.js'),'utf8');
const context={globalThis:{}};
vm.createContext(context);
vm.runInContext(source,context);
const api=context.globalThis.SemiconChartEngine;
if(!api) throw new Error('Chart engine missing');

const projects=[
  {company:'A',capex:{low:100,high:100}},
  {company:'A',capex:{low:50,high:50}},
  {company:'B',capex:{low:80,high:80}},
];
const projectModel=api.build({view:'projects',rows:projects});
if(projectModel.type!=='bar') throw new Error('Projects must default to bar');
if(projectModel.data[0].label!=='A' || projectModel.data[0].value!==150) throw new Error('Project aggregation mismatch');

const qualities=[
  {quality:'primary_source_extracted'},
  {quality:'primary_source_extracted'},
  {quality:'imported_unverified'},
];
const pie=api.build({view:'quality',rows:qualities,requestedType:'pie'});
if(pie.type!=='pie') throw new Error('Valid part-to-whole must allow pie');
if(!api.pieAllowed(pie.data)) throw new Error('Pie gate rejected valid composition');

const tooMany=Array.from({length:7},(_,i)=>({label:String(i),value:1}));
if(api.pieAllowed(tooMany)) throw new Error('Pie gate must reject >6 categories');

const active={
  concept_id:'revenue',unit:'USD',
  history:[
    {id:'a',period_end:'2026-Q1',value:100},
    {id:'b',period_end:'2026-Q2',value:120},
  ],
};
const line=api.build({view:'financials',rows:[active],activeRow:active});
if(line.type!=='line' || line.data.length!==2 || line.data[1].value!==120) throw new Error('Financial line mismatch');

console.log('chart_engine_contract=PASS');
