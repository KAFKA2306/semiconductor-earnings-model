import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { performance } from 'node:perf_hooks';

const source=fs.readFileSync(path.join(process.cwd(),'public/assets/workbench-data-engine.js'),'utf8');
const context={globalThis:{},performance};
vm.createContext(context);
vm.runInContext(source,context);
const api=context.globalThis.SemiconDataEngine;
if(!api) throw new Error('Workbench data engine missing');

const deterministicRows=[
  {id:'1',company:'B',country:'Japan',status:'Planned',capex:{high:20}},
  {id:'2',company:'A',country:'Japan',status:'Operational',capex:{high:30}},
  {id:'3',company:'C',country:'US',status:'Planned',capex:{high:10}},
];
const deterministic=api.filterSortRows(deterministicRows,{
  query:'',country:'',role:'',quality:'',status:'',watchlistOnly:false,watchlist:new Set(),
  includeFilters:[],excludeFilters:[],columnFilters:{status:'Plan'},
  sorts:[{key:'country',dir:'asc'},{key:'capex',dir:'desc'}],
});
if(deterministic.length!==2 || deterministic[0].id!=='1' || deterministic[1].id!=='3') throw new Error('Multi-sort/column-filter determinism failed');

const result=api.performanceFixture({count:500,iterations:100});
if(result.p95_ms>150) throw new Error('500-row filter/sort p95 exceeded 150ms: '+result.p95_ms.toFixed(2));

const workspaceSource=fs.readFileSync(path.join(process.cwd(),'public/assets/workspace-state.js'),'utf8');
const chartSource=fs.readFileSync(path.join(process.cwd(),'public/assets/chart-engine.js'),'utf8');
vm.runInContext(workspaceSource,context);
vm.runInContext(chartSource,context);
const workspaceApi=context.globalThis.SemiconWorkspaceState;
const chartApi=context.globalThis.SemiconChartEngine;
const state=workspaceApi.create({columns:['select','company','capex','status'],defaultSort:'company'});
const linked=new Map(Array.from({length:500},(_,i)=>['E'+i,{
  projects:Array.from({length:12},(_,j)=>({id:'p'+i+'-'+j})),
  financials:Array.from({length:24},(_,j)=>({id:'f'+i+'-'+j,concept_id:'revenue',value:j})),
  facilities:Array.from({length:12},(_,j)=>({id:'x'+i+'-'+j})),
  evidence:Array.from({length:12},(_,j)=>({id:'e'+i+'-'+j})),
  commitments:Array.from({length:12},(_,j)=>({id:'c'+i+'-'+j})),
}]));
const durations=[];
for(let i=0;i<100;i++){
  const row={id:'p'+i,entity_id:'E'+i,type:'project',company:'Company '+i,capex:{low:i,high:i+1}};
  const start=performance.now();
  workspaceApi.setActive(state,row);
  const contexts=linked.get(state.active.entityId);
  if(!contexts || Object.keys(contexts).length<5) throw new Error('Linked context propagation failed');
  chartApi.build({view:'projects',rows:[row],activeRow:row});
  durations.push(performance.now()-start);
}
durations.sort((a,b)=>a-b);
const linkedP95=durations[Math.ceil(durations.length*.95)-1];
if(linkedP95>100) throw new Error('ACTIVE to linked-context p95 exceeded 100ms: '+linkedP95.toFixed(2));

console.log('workbench_performance_contract=PASS rows='+result.count+' filter_sort_p95_ms='+result.p95_ms.toFixed(2)+' active_linked_p95_ms='+linkedP95.toFixed(2));
