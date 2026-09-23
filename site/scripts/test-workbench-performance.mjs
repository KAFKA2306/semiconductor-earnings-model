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

const result=api.performanceFixture({count:500,iterations:100});
if(result.p95_ms>150) throw new Error('500-row filter/sort p95 exceeded 150ms: '+result.p95_ms.toFixed(2));
console.log('workbench_performance_contract=PASS rows='+result.count+' p95_ms='+result.p95_ms.toFixed(2)+' max_ms='+result.max_ms.toFixed(2));
