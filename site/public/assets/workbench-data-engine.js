(() => {
  const cellValue = (row, key) => {
    if (key === 'select') return '';
    if (key === 'company') return row.company || row.name || row.entity_id || '';
    if (key === 'capex') {
      const cap = row.capex || {};
      return cap.high ?? cap.low ?? null;
    }
    if (key === 'capacity') return row.capacity_after ?? row.capacity_before ?? null;
    if (key === 'quality') return row.quality || '';
    return row[key] ?? '';
  };

  const filterSortRows = (rows, state) => {
    const needle=String(state.query || '').trim().toLowerCase();
    let out=rows.filter(row=>{
      if(state.country && row.country!==state.country) return false;
      if(state.role && row.role!==state.role) return false;
      if(state.quality && row.quality!==state.quality) return false;
      if(state.status && row.status!==state.status) return false;
      if(state.watchlistOnly && !state.watchlist?.has(row.entity_id)) return false;
      for(const [key,value] of Object.entries(state.columnFilters || {})){
        const needle=String(value || '').trim().toLowerCase();
        if(needle && !String(cellValue(row,key) ?? '').toLowerCase().includes(needle)) return false;
      }
      for(const item of state.includeFilters || []){
        if(String(cellValue(row,item.key) ?? '')!==String(item.value)) return false;
      }
      for(const item of state.excludeFilters || []){
        if(String(cellValue(row,item.key) ?? '')===String(item.value)) return false;
      }
      if(!needle) return true;
      const haystack=[
        row.company,row.name,row.ticker,row.entity_id,row.project_name,row.product,row.technology,
        row.location,row.status,row.event_type,row.evidence,row.customer,row.metric,row.source_system
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(needle);
    });
    const sorts=Array.isArray(state.sorts) && state.sorts.length ? state.sorts : (state.sortKey ? [{key:state.sortKey,dir:state.sortDir||'asc'}] : []);
    if(sorts.length){
      out=[...out].sort((a,b)=>{
        for(const sort of sorts){
          const av=cellValue(a,sort.key),bv=cellValue(b,sort.key);
          let cmp=0;
          if(av==null && bv!=null) cmp=1;
          else if(av!=null && bv==null) cmp=-1;
          else if(typeof av==='number' && typeof bv==='number') cmp=av-bv;
          else cmp=String(av ?? '').localeCompare(String(bv ?? ''),undefined,{numeric:true,sensitivity:'base'});
          if(cmp) return sort.dir==='desc' ? -cmp : cmp;
        }
        return 0;
      });
    }
    return out;
  };

  const percentile=(values,p)=>{
    const ordered=[...values].sort((a,b)=>a-b);
    return ordered[Math.min(ordered.length-1,Math.max(0,Math.ceil(ordered.length*p)-1))] || 0;
  };

  const performanceFixture = ({count=500,iterations=60}={}) => {
    const rows=Array.from({length:count},(_,i)=>({
      id:'row-'+i,entity_id:'E'+(i%120),company:'Company '+(i%120),ticker:'T'+i,
      country:i%3===0?'Japan':i%3===1?'US':'Korea',role:i%2?'Memory':'WFE',
      quality:i%4===0?'primary_source_extracted':'imported_unverified',
      status:i%5===0?'Operational':'Planned',project_name:'Fab project '+i,
      capex:{low:i*10,high:i*10+5},capacity_before:i,capacity_after:i+100,
      target_date:'2026-'+String((i%12)+1).padStart(2,'0')+'-01',
    }));
    const durations=[];
    for(let i=0;i<iterations;i++){
      const state={
        query:i%2?'Company':'Fab',country:i%3===0?'Japan':'',role:'',quality:'',status:'',
        watchlistOnly:false,watchlist:new Set(),includeFilters:[],excludeFilters:[],columnFilters:i%4===0?{status:'Plan'}:{},
        sortKey:i%2?'company':'capex',sortDir:i%3===0?'desc':'asc',
        sorts:i%5===0?[{key:'country',dir:'asc'},{key:'capex',dir:'desc'}]:[],
      };
      const start=performance.now();
      filterSortRows(rows,state);
      durations.push(performance.now()-start);
    }
    return {count,iterations,p95_ms:percentile(durations,.95),max_ms:Math.max(...durations)};
  };

  globalThis.SemiconDataEngine={cellValue,filterSortRows,performanceFixture};
})();
