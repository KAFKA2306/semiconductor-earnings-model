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
        query:'', country:'', role:'', quality:'', status:'',
        include:[], exclude:[],
      },
      table: {
        sortKey:defaultSort,
        sortDir:defaultDir === 'desc' ? 'desc' : 'asc',
        visibleColumns:new Set(columns),
      },
      inspector: {tab:'overview'},
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      emit(type) {
        for (const listener of listeners) listener(state, type);
      },
    };

    for (const key of ['query','country','role','quality','status']) defineAlias(state,key,'filter',key);
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
    },
    inspector:{...state.inspector},
  });

  globalThis.SemiconWorkspaceState = {
    SCHEMA_VERSION,
    create,
    setActive,
    clearActive,
    toggleSelected,
    setInspectorTab,
    snapshot,
  };
})();
