(() => {
  const SCHEMA_VERSION = 'workspace-state.v1';

  const defineAlias = (state, key, target, prop) => {
    Object.defineProperty(state, key, {
      enumerable: false,
      configurable: false,
      get: () => state[target][prop],
      set: value => { state[target][prop] = value; },
    });
  };

  const create = ({columns = [], defaultSort = '', defaultDir = 'asc'} = {}) => {
    const listeners = new Set();
    const state = {
      schemaVersion: SCHEMA_VERSION,
      active: {rowId:null, entityId:null, projectId:null, recordId:null},
      selected: new Set(),
      filter: {
        query:'', country:'', role:'', quality:'', status:'', watchlistOnly:false,
        include:[], exclude:[],
      },
      table: {
        sortKey:defaultSort,
        sortDir:defaultDir === 'desc' ? 'desc' : 'asc',
        visibleColumns:new Set(columns),
        columnOrder:[...columns],
        widths:{},
        pinned:new Set(['select','company'].filter(key=>columns.includes(key))),
      },
      analysis: {chartType:'auto', metric:null},
      watchlist:new Set(),
      widgets:{
        visible:new Set(['grid','chart','linked']),
        layout:'default',
        sizes:{chartHeight:170,inspectorWidth:390},
      },
      bottomPanel:{mode:'compare'},
      inspector: {tab:'overview'},
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      emit(type) {
        for (const listener of listeners) listener(state, type);
      },
    };

    for (const key of ['query','country','role','quality','status','watchlistOnly']) defineAlias(state,key,'filter',key);
    defineAlias(state,'includeFilters','filter','include');
    defineAlias(state,'excludeFilters','filter','exclude');
    defineAlias(state,'sortKey','table','sortKey');
    defineAlias(state,'sortDir','table','sortDir');
    defineAlias(state,'visibleColumns','table','visibleColumns');
    defineAlias(state,'activeId','active','rowId');

    return state;
  };

  const setActive = (state, row) => {
    state.active.rowId = row?.id || null;
    state.active.entityId = row?.entity_id || null;
    state.active.projectId = row?.type === 'project' ? row.id : (row?.project_id || null);
    state.active.recordId = row?.id || null;
    state.emit('active');
  };

  const clearActive = state => {
    state.active = {rowId:null, entityId:null, projectId:null, recordId:null};
    state.emit('active');
  };

  const toggleSelected = (state, id) => {
    if (!id) return;
    if (state.selected.has(id)) state.selected.delete(id);
    else state.selected.add(id);
    state.emit('selected');
  };

  const setInspectorTab = (state, tab) => {
    const next = ['overview','evidence','raw'].includes(tab) ? tab : 'overview';
    state.inspector.tab = next;
    state.emit('inspector');
  };

  const snapshot = state => ({
    schemaVersion:state.schemaVersion,
    active:{...state.active},
    selected:[...state.selected],
    filter:{
      ...state.filter,
      include:state.filter.include.map(item=>({...item})),
      exclude:state.filter.exclude.map(item=>({...item})),
    },
    table:{
      sortKey:state.table.sortKey,
      sortDir:state.table.sortDir,
      visibleColumns:[...state.table.visibleColumns],
      columnOrder:[...state.table.columnOrder],
      widths:{...state.table.widths},
      pinned:[...state.table.pinned],
    },
    analysis:{...state.analysis},
    watchlist:[...state.watchlist],
    widgets:{
      visible:[...state.widgets.visible],
      layout:state.widgets.layout,
      sizes:{...state.widgets.sizes},
    },
    bottomPanel:{...state.bottomPanel},
    inspector:{...state.inspector},
  });

  const restore = (state, saved, {columns=[]}={}) => {
    if (!saved || saved.schemaVersion !== SCHEMA_VERSION) throw new Error('Incompatible workspace schema');
    const available=new Set(columns);
    const filter=saved.filter || {};
    state.filter={
      query:String(filter.query || ''),
      country:String(filter.country || ''),
      role:String(filter.role || ''),
      quality:String(filter.quality || ''),
      status:String(filter.status || ''),
      watchlistOnly:Boolean(filter.watchlistOnly),
      include:Array.isArray(filter.include)?filter.include.map(item=>({...item})):[],
      exclude:Array.isArray(filter.exclude)?filter.exclude.map(item=>({...item})):[],
    };
    state.active={rowId:null,entityId:null,projectId:null,recordId:null,...(saved.active||{})};
    state.selected=new Set(Array.isArray(saved.selected)?saved.selected:[]);
    const table=saved.table || {};
    const order=Array.isArray(table.columnOrder)?table.columnOrder.filter(key=>available.has(key)):[];
    for(const key of columns) if(!order.includes(key)) order.push(key);
    state.table={
      sortKey:String(table.sortKey || ''),
      sortDir:table.sortDir==='desc'?'desc':'asc',
      visibleColumns:new Set(Array.isArray(table.visibleColumns)?table.visibleColumns.filter(key=>available.has(key)):columns),
      columnOrder:order,
      widths:table.widths && typeof table.widths==='object' ? {...table.widths} : {},
      pinned:new Set(Array.isArray(table.pinned)?table.pinned.filter(key=>available.has(key)):['select','company'].filter(key=>available.has(key))),
    };
    state.analysis={chartType:'auto',metric:null,...(saved.analysis||{})};
    state.watchlist=new Set(Array.isArray(saved.watchlist)?saved.watchlist:[]);
    const widgets=saved.widgets || {};
    state.widgets={
      visible:new Set(Array.isArray(widgets.visible)?widgets.visible:['grid','chart','linked']),
      layout:String(widgets.layout || 'default'),
      sizes:{chartHeight:170,inspectorWidth:390,...(widgets.sizes||{})},
    };
    state.bottomPanel={mode:'compare',...(saved.bottomPanel||{})};
    state.inspector={tab:'overview',...(saved.inspector||{})};
    state.emit('restore');
    return state;
  };

  globalThis.SemiconWorkspaceState = {
    SCHEMA_VERSION,
    create,
    setActive,
    clearActive,
    toggleSelected,
    setInspectorTab,
    snapshot,
    restore,
  };
})();
