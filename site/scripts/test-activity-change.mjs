import { classifyCanonicalChange } from '../src/lib/activity-change.mjs';

const cases=[
  [{event_type:'guidance'},'new_guidance'],
  [{evidence:'multi-year LTA with customers'},'customer_commitment'],
  [{project_name:'capacity expansion'},'capacity_change'],
  [{project_name:'new fab site'},'facility_change'],
  [{status:'stale refreshed'},'source_refresh'],
  [{status:'conflict detected'},'quality_change'],
  [{status:'construction ramp'},'project_update'],
  [{event_type:'disclosure'},'disclosure_update'],
];
for(const [row,expected] of cases){
  const actual=classifyCanonicalChange(row);
  if(actual!==expected) throw new Error(`Expected ${expected}, got ${actual}`);
}
console.log('activity_change_contract=PASS cases='+cases.length);
