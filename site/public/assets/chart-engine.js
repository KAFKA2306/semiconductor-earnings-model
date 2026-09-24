(() => {
  const finite = value => Number.isFinite(Number(value)) ? Number(value) : null;
  const capexValue = row => {
    const cap = row?.capex || {};
    const value = cap.high ?? cap.low ?? row?.capex_value ?? null;
    return finite(value);
  };
  const capacityValue = row => {
    const before=finite(row?.capacity_before);
    const after=finite(row?.capacity_after);
    if(after!=null && before!=null) return after-before;
    return after ?? before;
  };
  const grouped = (rows,key,valueFn) => {
    const map=new Map();
    for(const row of rows){
      const label=String(row?.[key] ?? '').trim();
      if(!label) continue;
      const v=valueFn(row);
      if(v==null) continue;
      map.set(label,(map.get(label)||0)+v);
    }
    return [...map.entries()].map(([label,value])=>({label,value,filterKey:key,filterValue:label}))
      .sort((a,b)=>b.value-a.value);
  };
  const counted = (rows,key) => {
    const map=new Map();
    for(const row of rows){
      const label=String(row?.[key] ?? 'Unknown').trim() || 'Unknown';
      map.set(label,(map.get(label)||0)+1);
    }
    return [...map.entries()].map(([label,value])=>({label,value,filterKey:key,filterValue:label}))
      .sort((a,b)=>b.value-a.value);
  };
  const pieAllowed = data => Array.isArray(data) && data.length>=2 && data.length<=6 &&
    data.every(d=>Number.isFinite(Number(d.value)) && Number(d.value)>=0) &&
    data.reduce((sum,d)=>sum+Number(d.value),0)>0;

  const lineFromActive = activeRow => {
    const history=Array.isArray(activeRow?.history) ? activeRow.history : [];
    const data=history.map(point=>({
      label:point.period_end || '',
      value:finite(point.value),
      filterKey:'target_date',
      filterValue:point.period_end || '',
      recordId:point.id || null,
      sourceUrl:point.source_url || null,
    })).filter(point=>point.label && point.value!=null);
    return data.length ? {type:'line',title:(activeRow.concept_id || 'Financial')+' history',data,valueLabel:activeRow.unit || 'Value'} : null;
  };

  const build = ({view,rows=[],activeRow=null,requestedType='auto'}={}) => {
    let model=null;
    if(view==='financials') model=lineFromActive(activeRow || rows[0]);
    else if(view==='projects'){
      const data=grouped(rows,'company',capexValue);
      model={type:'bar',title:'CapEx by company',data:data.length?data:counted(rows,'company'),valueLabel:data.length?'CapEx':'Projects'};
    } else if(view==='capacity'){
      const data=grouped(rows,'company',capacityValue);
      model={type:'bar',title:'Capacity change by company',data:data.length?data:counted(rows,'company'),valueLabel:data.length?'Change':'Projects'};
    } else if(view==='companies'){
      const data=rows.map(r=>({label:r.company || r.entity_id,value:finite(r.project_count) ?? 0,filterKey:'company',filterValue:r.company || r.entity_id}));
      model={type:'bar',title:'Tracked projects by company',data:data.sort((a,b)=>b.value-a.value),valueLabel:'Projects'};
    } else if(view==='evidence'){
      model={type:'bar',title:'Evidence quality composition',data:counted(rows,'quality'),valueLabel:'Records'};
    } else if(view==='quality'){
      model={type:'bar',title:'Data quality composition',data:counted(rows,'quality'),valueLabel:'Records'};
    } else if(view==='activity'){
      model={type:'bar',title:'Activity by event type',data:counted(rows,'event_type'),valueLabel:'Events'};
    } else if(view==='facilities'){
      model={type:'bar',title:'Facilities by country',data:counted(rows,'country'),valueLabel:'Facilities'};
    }
    if(!model || !model.data?.length) return {type:'empty',title:'No chartable data',data:[]};

    const wanted=requestedType==='auto' ? model.type : requestedType;
    if(wanted==='pie' && pieAllowed(model.data)) model.type='pie';
    else if(wanted==='bar' && model.type!=='line') model.type='bar';
    else if(wanted==='line' && model.type!=='line') model.type='bar';
    return model;
  };

  globalThis.SemiconChartEngine={build,pieAllowed,capexValue,capacityValue};
})();
