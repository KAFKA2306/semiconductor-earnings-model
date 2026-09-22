import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const source = fs.readFileSync(path.join(process.cwd(),'public/assets/workspace-state.js'),'utf8');
const context = {globalThis:{}};
vm.createContext(context);
vm.runInContext(source,context);

const api=context.globalThis.SemiconWorkspaceState;
if(!api) throw new Error('WorkspaceState API missing');
if(api.SCHEMA_VERSION!=='workspace-state.v1') throw new Error('Unexpected schema version');

const state=api.create({columns:['select','company','status'],defaultSort:'company',defaultDir:'asc'});
if(state.activeId!==null || state.active.entityId!==null) throw new Error('ACTIVE must start empty');
if(state.selected.size!==0) throw new Error('SELECTED must start empty');
if(state.filter.query!=='' || state.includeFilters.length!==0) throw new Error('FILTER must start empty');

state.query='Kioxia';
state.country='Japan';
state.includeFilters=[{key:'quality',value:'primary_source_extracted'}];
if(state.filter.query!=='Kioxia' || state.filter.country!=='Japan' || state.filter.include.length!==1) {
  throw new Error('Flat compatibility aliases must mutate FILTER authority');
}

const row={id:'CAPEX-JP285A-1',entity_id:'JP:285A',type:'project'};
api.setActive(state,row);
if(state.active.rowId!==row.id || state.active.entityId!=='JP:285A' || state.active.projectId!==row.id) {
  throw new Error('ACTIVE propagation failed');
}

api.toggleSelected(state,row.id);
if(!state.selected.has(row.id) || state.active.rowId!==row.id) throw new Error('SELECTED must be independent of ACTIVE');
api.toggleSelected(state,row.id);
if(state.selected.has(row.id)) throw new Error('SELECTED toggle failed');

api.setInspectorTab(state,'raw');
if(state.inspector.tab!=='raw') throw new Error('Inspector tab state failed');
api.setInspectorTab(state,'bogus');
if(state.inspector.tab!=='overview') throw new Error('Invalid tab must fail closed to overview');

const snapshot=api.snapshot(state);
if(snapshot.schemaVersion!=='workspace-state.v1') throw new Error('Snapshot schema missing');
if(!(snapshot.table.visibleColumns.includes('company'))) throw new Error('Visible columns snapshot missing');
if(snapshot.filter.query!=='Kioxia') throw new Error('Filter snapshot missing');

api.clearActive(state);
if(state.activeId!==null || state.active.entityId!==null) throw new Error('ACTIVE clear failed');

console.log('workspace_state_contract=PASS schema='+api.SCHEMA_VERSION);
