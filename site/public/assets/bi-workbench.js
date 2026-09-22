(() => {
  const root = document.querySelector('[data-workbench]');
  if (!root) return;

  const payloadEl = document.getElementById('workbench-data');
  const payload = payloadEl ? JSON.parse(payloadEl.textContent || '{}') : {};
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  const columns = Array.isArray(payload.columns) ? payload.columns : [];
  const linkedByEntity = payload.linkedByEntity || {};
  const workspaceApi = globalThis.SemiconWorkspaceState;
  if (!workspaceApi) throw new Error('WorkspaceState v1 is required');
  const chartEngine = globalThis.SemiconChartEngine;
  if (!chartEngine) throw new Error('Chart engine is required');
  const state = workspaceApi.create({
    columns:columns.map(c=>c.key),
    defaultSort:payload.defaultSort || '',
    defaultDir:payload.defaultDir === 'desc' ? 'desc' : 'asc',
  });

  const q = sel => root.querySelector(sel);
  const qa = sel => [...root.querySelectorAll(sel)];
  const tableBody = q('[data-table-body]');
  const tableWrap = q('.wb-table-wrap');
  const resultCount = q('[data-result-count]');
  const inspector = q('[data-inspector]');
  const workspace = q('[data-workspace]');
  const compareBar = q('[data-compare-bar]');
  const compareCount = q('[data-compare-count]');
  const searchInput = q('[data-search]');
  const command = q('[data-command]');
  const commandInput = command?.querySelector('[data-command-input]');
  const commandResults = command?.querySelector('[data-command-results]');
  const columnDialog = q('[data-column-dialog]');
  const columnList = q('[data-column-list]');
  const compareDialog = q('[data-compare-dialog]');
  const compareBody = q('[data-compare-body]');
  const viewsDialog = q('[data-views-dialog]');
  const viewsBody = q('[data-views-body]');
  const exportDialog = q('[data-export-dialog]');
  const mobileNavDialog = q('[data-mobile-nav-dialog]');
  const linkedStrip = q('[data-linked-strip]');
  const chartPanel = q('[data-chart-panel]');
  const crossFilterChips = q('[data-cross-filter-chips]');

  const TABLE_LAYOUT_KEY='semicon:table-layout:' + (payload.view || 'projects');
  const orderedColumns = () => {
    const map=new Map(columns.map(col=>[col.key,col]));
    return state.table.columnOrder.map(key=>map.get(key)).filter(Boolean);
  };
  const loadTableLayout = () => {
    try {
      const saved=JSON.parse(localStorage.getItem(TABLE_LAYOUT_KEY) || 'null');
      if(!saved || saved.schema_version!=='table-layout.v1') return;
      const available=new Set(columns.map(c=>c.key));
      const order=Array.isArray(saved.order) ? saved.order.filter(key=>available.has(key)) : [];
      for(const col of columns) if(!order.includes(col.key)) order.push(col.key);
      state.table.columnOrder=order;
      state.table.widths=saved.widths && typeof saved.widths==='object' ? saved.widths : {};
      state.table.pinned=new Set(Array.isArray(saved.pinned) ? saved.pinned.filter(key=>available.has(key)) : ['select','company'].filter(key=>available.has(key)));
    } catch {}
  };
  const saveTableLayout = () => {
    localStorage.setItem(TABLE_LAYOUT_KEY,JSON.stringify({
      schema_version:'table-layout.v1',
      order:[...state.table.columnOrder],
      widths:{...state.table.widths},
      pinned:[...state.table.pinned],
    }));
  };
  const moveColumn = (key,delta) => {
    const order=[...state.table.columnOrder];
    const index=order.indexOf(key);
    const target=index+delta;
    if(index<0 || target<0 || target>=order.length || key==='select' || order[target]==='select') return;
    [order[index],order[target]]=[order[target],order[index]];
    state.table.columnOrder=order;
    saveTableLayout();
  };

  const escapeHtml = value => String(value ?? '')
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');

  const formatCapex = row => {
    const capex = row.capex;
    if (!capex || (capex.low == null && capex.high == null)) return '<span class="wb-null">—</span>';
    const cur = capex.currency || row.currency || '';
    const scale = capex.scale || '';
    const fmt = v => {
      if (v == null) return null;
      const n = Number(v);
      if (scale === 'million') {
        if (n >= 1000) return (n / 1000).toLocaleString(undefined,{maximumFractionDigits:1}) + 'B';
        return n.toLocaleString() + 'M';
      }
      return n.toLocaleString();
    };
    const low = fmt(capex.low);
    const high = fmt(capex.high);
    const body = low != null && high != null && low !== high ? low + '–' + high : (high ?? low);
    const qualifier = capex.low == null && capex.high != null ? '≤' : (capex.high == null && capex.low != null ? '≥' : '');
    return escapeHtml(cur) + ' ' + qualifier + escapeHtml(body || '—');
  };

  const formatCapacity = row => {
    if (row.capacity_before == null && row.capacity_after == null) return '<span class="wb-null">—</span>';
    if (row.capacity_before != null && row.capacity_after != null) return '<span class="wb-capacity">' + escapeHtml(row.capacity_before) + ' → ' + escapeHtml(row.capacity_after) + '</span>';
    return escapeHtml(row.capacity_after ?? row.capacity_before);
  };

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

  const cellHtml = (row, col) => {
    const key = col.key;
    if (key === 'select') return '<input class="wb-checkbox" type="checkbox" aria-label="Select row" data-select-row="' + escapeHtml(row.id) + '"' + (state.selected.has(row.id) ? ' checked' : '') + '>';
    if (key === 'company') {
      return '<span class="main-cell">' + escapeHtml(row.company || row.name || row.entity_id) + '</span><span class="sub">' + escapeHtml(row.ticker || row.entity_id || '') + '</span>';
    }
    if (key === 'capex') return formatCapex(row);
    if (key === 'capacity') return formatCapacity(row);
    if (key === 'quality') return '<span class="wb-quality ' + escapeHtml(row.quality || '') + '"><i class="wb-source-dot ' + escapeHtml(row.quality || '') + '"></i>' + escapeHtml(row.quality_label || row.quality || 'unknown') + '</span>';
    if (key === 'status') return row.status ? '<span class="wb-status" title="' + escapeHtml(row.status) + '">' + escapeHtml(row.status) + '</span>' : '<span class="wb-null">—</span>';
    const value = row[key];
    return value == null || value === '' ? '<span class="wb-null">—</span>' : escapeHtml(value);
  };

  const readUrl = () => {
    const params = new URLSearchParams(location.search);
    state.query = params.get('q') || '';
    state.country = params.get('country') || '';
    state.role = params.get('role') || '';
    state.quality = params.get('quality') || '';
    state.status = params.get('status') || '';
    state.sortKey = params.get('sort') || state.sortKey;
    state.sortDir = params.has('dir') ? (params.get('dir') === 'desc' ? 'desc' : 'asc') : (payload.defaultDir === 'desc' ? 'desc' : 'asc');
    state.activeId = params.get('row') || null;
    const selected = (params.get('compare') || '').split(',').filter(Boolean);
    state.selected = new Set(selected);
    const cols = (params.get('cols') || '').split(',').filter(Boolean);
    if (cols.length) state.visibleColumns = new Set(cols.filter(key => columns.some(c => c.key === key)));
    const parsePair = value => {
      const idx = value.indexOf('=');
      return idx > 0 ? {key:value.slice(0,idx), value:value.slice(idx+1)} : null;
    };
    state.includeFilters = params.getAll('f').map(parsePair).filter(Boolean);
    state.excludeFilters = params.getAll('x').map(parsePair).filter(Boolean);
    if (searchInput) searchInput.value = state.query;
    for (const key of ['country','role','quality','status']) {
      const el = q('[data-filter="' + key + '"]');
      if (el) el.value = state[key];
    }
  };

  const writeUrl = () => {
    const params = new URLSearchParams();
    if (state.query) params.set('q', state.query);
    if (state.country) params.set('country', state.country);
    if (state.role) params.set('role', state.role);
    if (state.quality) params.set('quality', state.quality);
    if (state.status) params.set('status', state.status);
    if (state.sortKey) params.set('sort', state.sortKey);
    if (state.sortDir === 'desc') params.set('dir','desc');
    if (state.activeId) params.set('row', state.activeId);
    if (state.selected.size) params.set('compare',[...state.selected].join(','));
    const defaultCols = columns.map(c => c.key);
    const visible = [...state.visibleColumns];
    if (visible.length !== defaultCols.length || visible.some((key,idx)=>key !== defaultCols[idx])) params.set('cols',visible.join(','));
    for (const item of state.includeFilters) params.append('f',item.key + '=' + item.value);
    for (const item of state.excludeFilters) params.append('x',item.key + '=' + item.value);
    const qs = params.toString();
    history.replaceState(null,'',location.pathname + (qs ? '?' + qs : ''));
  };

  const filteredRows = () => {
    const needle = state.query.trim().toLowerCase();
    let out = rows.filter(row => {
      if (state.country && row.country !== state.country) return false;
      if (state.role && row.role !== state.role) return false;
      if (state.quality && row.quality !== state.quality) return false;
      if (state.status && row.status !== state.status) return false;
      for (const item of state.includeFilters) {
        if (String(cellValue(row,item.key) ?? '') !== item.value) return false;
      }
      for (const item of state.excludeFilters) {
        if (String(cellValue(row,item.key) ?? '') === item.value) return false;
      }
      if (!needle) return true;
      const haystack = [
        row.company,row.name,row.ticker,row.entity_id,row.project_name,row.product,row.technology,
        row.location,row.status,row.event_type,row.evidence,row.customer,row.metric,row.source_system
      ].filter(Boolean).join(' ').toLowerCase();
      return haystack.includes(needle);
    });
    if (state.sortKey) {
      out = [...out].sort((a,b) => {
        const av = cellValue(a,state.sortKey);
        const bv = cellValue(b,state.sortKey);
        if (av == null && bv != null) return 1;
        if (av != null && bv == null) return -1;
        if (typeof av === 'number' && typeof bv === 'number') return av - bv;
        return String(av ?? '').localeCompare(String(bv ?? ''),undefined,{numeric:true,sensitivity:'base'});
      });
      if (state.sortDir === 'desc') out.reverse();
    }
    return out;
  };

  const renderSortState = () => {
    qa('[data-sort]').forEach(th => {
      const key = th.getAttribute('data-sort');
      const active = key && key === state.sortKey;
      th.setAttribute('aria-sort', active ? (state.sortDir === 'desc' ? 'descending' : 'ascending') : 'none');
      if (active) th.setAttribute('data-sort-dir',state.sortDir);
      else th.removeAttribute('data-sort-dir');
    });
  };

  const applyColumnLayout = () => {
    const headRow=q('.wb-table thead tr');
    if(!headRow) return;
    for(const col of orderedColumns()){
      const th=q('[data-col="' + col.key + '"]');
      if(th) headRow.appendChild(th);
    }
    let left=0;
    for(const col of orderedColumns()){
      const key=col.key;
      const th=q('[data-col="' + key + '"]');
      if(!th) continue;
      const width=Number(state.table.widths[key] || col.width || th.getBoundingClientRect().width || 120);
      if(state.table.widths[key]){
        th.style.width=width+'px';th.style.minWidth=width+'px';th.style.maxWidth=width+'px';
        qa('td[data-cell-key="' + key + '"]').forEach(td=>{td.style.width=width+'px';td.style.minWidth=width+'px';td.style.maxWidth=width+'px'});
      }
      const pinned=state.table.pinned.has(key);
      th.classList.toggle('wb-pinned',pinned);
      qa('td[data-cell-key="' + key + '"]').forEach(td=>td.classList.toggle('wb-pinned',pinned));
      if(pinned){
        th.style.left=left+'px';
        qa('td[data-cell-key="' + key + '"]').forEach(td=>td.style.left=left+'px');
        left+=width;
      } else {
        th.style.left='';
        qa('td[data-cell-key="' + key + '"]').forEach(td=>td.style.left='');
      }
    }
  };
  const ensureColumnResizers = () => {
    qa('[data-col]').forEach(th=>{
      const key=th.getAttribute('data-col');
      if(!key || th.querySelector('[data-resize-col]')) return;
      const handle=document.createElement('span');
      handle.className='wb-col-resizer';
      handle.setAttribute('data-resize-col',key);
      handle.addEventListener('pointerdown',ev=>{
        ev.preventDefault();ev.stopPropagation();
        const startX=ev.clientX;
        const startWidth=th.getBoundingClientRect().width;
        const move=e=>{
          const next=Math.max(34,Math.min(480,startWidth+(e.clientX-startX)));
          state.table.widths[key]=Math.round(next);
          applyColumnLayout();
        };
        const up=()=>{
          document.removeEventListener('pointermove',move);
          document.removeEventListener('pointerup',up);
          saveTableLayout();
        };
        document.addEventListener('pointermove',move);
        document.addEventListener('pointerup',up);
      });
      th.appendChild(handle);
    });
  };

  const renderTable = () => {
    renderSortState();
    qa('[data-col]').forEach(th => th.classList.toggle('wb-hidden', !state.visibleColumns.has(th.getAttribute('data-col'))));
    const visible = filteredRows();
    if (resultCount) resultCount.textContent = visible.length.toLocaleString();
    if (!tableBody) return;
    if (!visible.length) {
      tableBody.innerHTML = '<tr><td colspan="' + columns.length + '"><div class="wb-empty">No rows match the current screen.</div></td></tr>';
      return;
    }
    const VIRTUALIZE_AT = 200;
    const ROW_HEIGHT = 35;
    const BUFFER = 12;
    let renderRows = visible;
    let topPad = 0;
    let bottomPad = 0;
    if (tableWrap && visible.length > VIRTUALIZE_AT) {
      const viewportRows = Math.ceil(tableWrap.clientHeight / ROW_HEIGHT);
      const start = Math.max(0, Math.floor(tableWrap.scrollTop / ROW_HEIGHT) - BUFFER);
      const end = Math.min(visible.length, start + viewportRows + BUFFER * 2);
      renderRows = visible.slice(start,end);
      topPad = start * ROW_HEIGHT;
      bottomPad = (visible.length - end) * ROW_HEIGHT;
      tableWrap.dataset.virtualized = 'true';
    } else if (tableWrap) {
      tableWrap.dataset.virtualized = 'false';
    }
    const visibleColCount = orderedColumns().filter(c => state.visibleColumns.has(c.key)).length;
    const rowHtml = renderRows.map(row => {
      const selected = state.activeId === row.id ? ' selected' : '';
      return '<tr class="' + selected.trim() + '" data-row="' + escapeHtml(row.id) + '" tabindex="0">' +
        orderedColumns().filter(c => state.visibleColumns.has(c.key)).map(col => {
          const raw = cellValue(row,col.key);
          return '<td class="' + (col.numeric ? 'num' : '') + '" data-cell-key="' + escapeHtml(col.key) + '" data-cell-value="' + escapeHtml(raw == null ? '' : String(raw)) + '">' + cellHtml(row,col) + '</td>';
        }).join('') +
        '</tr>';
    }).join('');
    tableBody.innerHTML =
      (topPad ? '<tr class="wb-virtual-spacer"><td colspan="' + visibleColCount + '" style="height:' + topPad + 'px"></td></tr>' : '') +
      rowHtml +
      (bottomPad ? '<tr class="wb-virtual-spacer"><td colspan="' + visibleColCount + '" style="height:' + bottomPad + 'px"></td></tr>' : '');
    qa('[data-select-row]').forEach(box => box.addEventListener('click', ev => {
      ev.stopPropagation();
      toggleSelected(box.getAttribute('data-select-row'));
    }));
    qa('[data-row]').forEach(tr => {
      tr.addEventListener('click', ev => {
        if (ev.target.closest('input,button,a')) return;
        openInspector(tr.getAttribute('data-row'));
      });
      tr.addEventListener('keydown', ev => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openInspector(tr.getAttribute('data-row')); }
      });
    });
    qa('td[data-cell-key]').forEach(td => td.addEventListener('contextmenu', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      openCellMenu(td, ev.clientX, ev.clientY);
    }));
    ensureColumnResizers();
    applyColumnLayout();
    renderChart();
  };

  const renderCrossFilterChips = () => {
    if (!crossFilterChips) return;
    const items = [
      ...state.includeFilters.map((item,index)=>({...item,mode:'include',index})),
      ...state.excludeFilters.map((item,index)=>({...item,mode:'exclude',index})),
    ];
    crossFilterChips.innerHTML = items.map(item =>
      '<button type="button" class="wb-filter-chip ' + item.mode + '" data-filter-chip-mode="' + item.mode + '" data-filter-chip-index="' + item.index + '">' +
      '<span>' + (item.mode === 'exclude' ? '≠ ' : '= ') + escapeHtml(item.key) + ': ' + escapeHtml(item.value) + '</span><b>×</b></button>'
    ).join('');
    [...crossFilterChips.querySelectorAll('[data-filter-chip-mode]')].forEach(btn=>btn.addEventListener('click',()=>{
      const mode=btn.getAttribute('data-filter-chip-mode');
      const index=Number(btn.getAttribute('data-filter-chip-index'));
      if(mode==='exclude') state.excludeFilters.splice(index,1); else state.includeFilters.splice(index,1);
      renderCrossFilterChips(); renderTable(); writeUrl();
    }));
  };

  let activeCellMenu = null;
  const closeCellMenu = () => {
    activeCellMenu?.remove();
    activeCellMenu = null;
  };
  const addCrossFilter = (mode,key,value) => {
    if (!key || key === 'select' || value === '') return;
    const target = mode === 'exclude' ? state.excludeFilters : state.includeFilters;
    if (!target.some(item => item.key === key && item.value === value)) target.push({key,value});
    closeCellMenu();
    renderCrossFilterChips();
    renderTable();
    writeUrl();
    toast((mode === 'exclude' ? 'Excluded ' : 'Filtered ') + key + ': ' + value);
  };
  const openCellMenu = (td,x,y) => {
    closeCellMenu();
    const key=td.getAttribute('data-cell-key') || '';
    const value=td.getAttribute('data-cell-value') || '';
    const rowId=td.closest('[data-row]')?.getAttribute('data-row') || '';
    const rowObj=rows.find(r=>r.id===rowId);
    const entityId=rowObj?.entity_id || '';
    if(key === 'select') return;
    const menu=document.createElement('div');
    menu.className='wb-cell-menu';
    menu.style.left=Math.min(x,window.innerWidth-230)+'px';
    menu.style.top=Math.min(y,window.innerHeight-190)+'px';
    menu.innerHTML=
      '<button type="button" data-cell-action="include">Filter by <strong>' + escapeHtml(value || 'blank') + '</strong></button>' +
      '<button type="button" data-cell-action="exclude">Exclude <strong>' + escapeHtml(value || 'blank') + '</strong></button>' +
      '<button type="button" data-cell-action="open">Open underlying row</button>' +
      (entityId ? '<button type="button" data-cell-action="projects">Related projects</button><button type="button" data-cell-action="financials">Related financials</button><button type="button" data-cell-action="evidence">Related evidence</button>' : '') +
      '<button type="button" data-cell-action="copy">Copy value</button>' +
      ((state.includeFilters.length || state.excludeFilters.length) ? '<button type="button" data-cell-action="clear">Clear cross-filters</button>' : '');
    document.body.appendChild(menu);
    activeCellMenu=menu;
    menu.querySelector('[data-cell-action="include"]')?.addEventListener('click',()=>addCrossFilter('include',key,value));
    menu.querySelector('[data-cell-action="exclude"]')?.addEventListener('click',()=>addCrossFilter('exclude',key,value));
    menu.querySelector('[data-cell-action="open"]')?.addEventListener('click',()=>{closeCellMenu();openInspector(rowId)});
    for (const kind of ['projects','financials','evidence']) {
      menu.querySelector('[data-cell-action="' + kind + '"]')?.addEventListener('click',()=>{
        closeCellMenu();
        const target = kind === 'projects' ? '' : kind + '/';
        location.href=(payload.base || '/') + target + '?q=' + encodeURIComponent(entityId);
      });
    }
    menu.querySelector('[data-cell-action="copy"]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(value);toast('Value copied')}catch{toast('Copy failed')}closeCellMenu()});
    menu.querySelector('[data-cell-action="clear"]')?.addEventListener('click',()=>{state.includeFilters=[];state.excludeFilters=[];closeCellMenu();renderCrossFilterChips();renderTable();writeUrl();toast('Cross-filters cleared')});
  };

  const renderColumnDialog = () => {
    if (!columnList) return;
    const available = new Set(columns.map(c=>c.key));
    const presets = {
      default: columns.map(c=>c.key),
      compact: ['select','company','project_name','concept_id','capex','capacity','status','target_date','value','unit'].filter(k=>available.has(k)),
      evidence: ['select','company','project_name','concept_id','event_type','status','target_date','source_system','quality'].filter(k=>available.has(k)),
    };
    columnList.innerHTML =
      '<div class="wb-column-presets"><button type="button" data-column-preset="default">Default</button><button type="button" data-column-preset="compact">Compact</button><button type="button" data-column-preset="evidence">Evidence</button></div>' +
      '<div class="wb-column-grid">' +
      orderedColumns().map((col,index) => {
        const locked = col.key === 'select' || col.key === 'company';
        const pinned=state.table.pinned.has(col.key);
        return '<div class="wb-column-item"><label><input type="checkbox" data-column-toggle="' + escapeHtml(col.key) + '"' +
          (state.visibleColumns.has(col.key) ? ' checked' : '') + (locked ? ' disabled' : '') + '><span>' + escapeHtml(col.label || col.key) + '</span></label>' +
          '<span class="wb-column-actions"><button type="button" data-col-up="' + escapeHtml(col.key) + '" aria-label="Move column left"' + (index===0?' disabled':'') + '>←</button>' +
          '<button type="button" data-col-down="' + escapeHtml(col.key) + '" aria-label="Move column right"' + (index===columns.length-1?' disabled':'') + '>→</button>' +
          '<button type="button" data-col-pin="' + escapeHtml(col.key) + '" aria-pressed="' + (pinned?'true':'false') + '">' + (pinned?'Unpin':'Pin') + '</button></span></div>';
      }).join('') + '</div>';
    [...columnList.querySelectorAll('[data-column-toggle]')].forEach(input => input.addEventListener('change',() => {
      const key=input.getAttribute('data-column-toggle');
      if(input.checked) state.visibleColumns.add(key); else state.visibleColumns.delete(key);
      state.visibleColumns.add('select'); state.visibleColumns.add('company');
      renderTable(); writeUrl();
    }));
    [...columnList.querySelectorAll('[data-col-up]')].forEach(btn=>btn.addEventListener('click',()=>{moveColumn(btn.getAttribute('data-col-up'),-1);renderColumnDialog();renderTable();writeUrl()}));
    [...columnList.querySelectorAll('[data-col-down]')].forEach(btn=>btn.addEventListener('click',()=>{moveColumn(btn.getAttribute('data-col-down'),1);renderColumnDialog();renderTable();writeUrl()}));
    [...columnList.querySelectorAll('[data-col-pin]')].forEach(btn=>btn.addEventListener('click',()=>{
      const key=btn.getAttribute('data-col-pin');
      if(state.table.pinned.has(key)) state.table.pinned.delete(key); else state.table.pinned.add(key);
      saveTableLayout();renderColumnDialog();renderTable();
    }));
    [...columnList.querySelectorAll('[data-column-preset]')].forEach(btn=>btn.addEventListener('click',()=>{
      state.visibleColumns = new Set(presets[btn.getAttribute('data-column-preset')] || presets.default);
      state.visibleColumns.add('select'); state.visibleColumns.add('company');
      renderColumnDialog(); renderTable(); writeUrl();
    }));
  };

  const compareValue = (row, key) => {
    if (key === 'capex') return formatCapex(row).replace(/<[^>]+>/g,'');
    if (key === 'capacity') {
      if (row.capacity_before == null && row.capacity_after == null) return '—';
      return String(row.capacity_before ?? '—') + ' → ' + String(row.capacity_after ?? '—');
    }
    const v = cellValue(row,key);
    return v == null || v === '' ? '—' : String(v);
  };

  const openCompare = () => {
    if (!compareDialog || !compareBody) return;
    const selectedRows = rows.filter(r => state.selected.has(r.id));
    if (!selectedRows.length) return;
    const compareCols = orderedColumns().filter(c => !['select','company'].includes(c.key) && state.visibleColumns.has(c.key));
    compareBody.innerHTML = '<table class="wb-compare-table"><thead><tr><th>Metric</th>' +
      selectedRows.map(r=>'<th>' + escapeHtml(r.company || r.name || r.id) + '<br><small>' + escapeHtml(r.project_name || r.ticker || r.entity_id || '') + '</small></th>').join('') +
      '</tr></thead><tbody>' +
      compareCols.map(col=>'<tr><td class="row-label">' + escapeHtml(col.label) + '</td>' +
        selectedRows.map(r=>'<td class="' + (col.numeric?'num':'') + '">' + escapeHtml(compareValue(r,col.key)) + '</td>').join('') + '</tr>').join('') +
      '</tbody></table>';
    compareDialog.showModal();
  };

  const renderCompare = () => {
    if (!compareBar || !compareCount) return;
    compareCount.textContent = state.selected.size;
    compareBar.classList.toggle('open',state.selected.size > 0);
  };

  const metric = (label,value) => '<div class="wb-metric"><span>' + escapeHtml(label) + '</span><strong>' + (value || '<span class="wb-null">—</span>') + '</strong></div>';
  const formatFinancialValue = row => {
    if (row.value == null) return '<span class="wb-null">—</span>';
    const n=Number(row.value);
    if(!Number.isFinite(n)) return escapeHtml(row.value);
    if(row.unit==='USD' || row.unit==='JPY'){
      if(Math.abs(n)>=1e9) return escapeHtml(row.unit) + ' ' + (n/1e9).toLocaleString(undefined,{maximumFractionDigits:2}) + 'B';
      if(Math.abs(n)>=1e6) return escapeHtml(row.unit) + ' ' + (n/1e6).toLocaleString(undefined,{maximumFractionDigits:2}) + 'M';
    }
    if(row.unit==='ratio') return (n*100).toFixed(1) + '%';
    return n.toLocaleString();
  };

  const financialHistoryHtml = row => {
    const history = Array.isArray(row.history) ? row.history.filter(p => Number.isFinite(Number(p.value))) : [];
    if (row.type !== 'financial' || !history.length) return '';
    const values = history.map(p=>Number(p.value));
    const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
    const width=320, height=86, pad=8;
    const points = history.map((p,i)=>{
      const x = history.length === 1 ? width/2 : pad + i * ((width-pad*2)/(history.length-1));
      const y = height-pad - ((Number(p.value)-min)/span)*(height-pad*2);
      return x.toFixed(1)+','+y.toFixed(1);
    }).join(' ');
    const rowsHtml = [...history].reverse().map(p=>
      '<tr><td>' + escapeHtml(p.period_end || '—') + '</td><td class="num">' + formatFinancialValue(p) + '</td><td>' +
      (p.source_url ? '<a href="' + escapeHtml(p.source_url) + '" target="_blank" rel="noreferrer">' + escapeHtml(p.source_tier || 'source') + ' ↗</a>' : escapeHtml(p.source_tier || '—')) +
      '</td></tr>'
    ).join('');
    return '<div class="wb-section wb-history"><h3>History · chart + underlying observations</h3>' +
      '<svg class="wb-history-chart" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="Financial history chart">' +
      '<polyline points="' + points + '" vector-effect="non-scaling-stroke"></polyline>' +
      history.map((p,i)=>{
        const xy=points.split(' ')[i].split(',');
        return '<circle cx="'+xy[0]+'" cy="'+xy[1]+'" r="2.5"><title>'+escapeHtml((p.period_end||'')+' '+String(p.value)+' '+(p.unit||''))+'</title></circle>';
      }).join('') + '</svg>' +
      '<div class="wb-history-table-wrap"><table class="wb-history-table"><thead><tr><th>Period</th><th>Value</th><th>Source</th></tr></thead><tbody>' + rowsHtml + '</tbody></table></div></div>';
  };

  const linkedWorkspaceHtml = row => {
    const linked = linkedByEntity[row.entity_id] || {};
    const specs = [
      ['projects','Projects',''],
      ['financials','Financials','financials/'],
      ['facilities','Facilities','facilities/'],
      ['evidence','Evidence','evidence/'],
      ['commitments','Commitments','evidence/'],
    ];
    const cards = specs.map(([key,label,route]) => {
      const items = Array.isArray(linked[key]) ? linked[key] : [];
      const preview = items.slice(0,3).map(item => {
        const name = item.project_name || item.concept_id || item.facility_name || item.customer_name || item.event_type || item.id || item.commitment_id || 'record';
        const meta = item.target_date || item.period_end || item.status || item.quality || '';
        return '<li><strong>' + escapeHtml(name) + '</strong>' + (meta ? '<small>' + escapeHtml(meta) + '</small>' : '') + '</li>';
      }).join('');
      return '<section class="wb-linked-card"><button type="button" data-linked-route="' + escapeHtml(route) + '" data-linked-entity="' + escapeHtml(row.entity_id || '') + '"><span>' + escapeHtml(label) + '</span><b>' + items.length + ' ↗</b></button>' +
        (preview ? '<ul>' + preview + '</ul>' : '<p class="wb-null">No canonical records</p>') + '</section>';
    }).join('');
    return '<div class="wb-section wb-linked"><h3>Linked workspace</h3><div class="wb-linked-grid">' + cards + '</div></div>';
  };

  const renderLinkedStrip = () => {
    if (!linkedStrip) return;
    const row = rows.find(r=>r.id===state.active.rowId);
    if (!row?.entity_id) {
      linkedStrip.hidden = true;
      linkedStrip.innerHTML = '';
      return;
    }
    const linked = linkedByEntity[row.entity_id] || {};
    const specs = [
      ['Projects',linked.projects],
      ['Financials',linked.financials],
      ['Facilities',linked.facilities],
      ['Evidence',linked.evidence],
      ['Commitments',linked.commitments],
    ];
    linkedStrip.innerHTML =
      '<strong>' + escapeHtml(row.company || row.name || row.entity_id) + '</strong>' +
      specs.map(([label,items])=>'<span><b>' + (Array.isArray(items)?items.length:0) + '</b> ' + label + '</span>').join('');
    linkedStrip.hidden = false;
  };

  const applyInspectorTab = tab => {
    workspaceApi.setInspectorTab(state,tab);
    qa('[data-inspector-tab]').forEach(btn=>{
      const active=btn.getAttribute('data-inspector-tab')===state.inspector.tab;
      btn.classList.toggle('active',active);
      btn.setAttribute('aria-selected',active?'true':'false');
      btn.setAttribute('tabindex',active?'0':'-1');
    });
    qa('[data-inspector-pane]').forEach(pane=>{
      pane.hidden=pane.getAttribute('data-inspector-pane')!==state.inspector.tab;
    });
  };

  const inspectorHtml = row => {
    const src = row.source_url ? '<a class="wb-source-link" href="' + escapeHtml(row.source_url) + '" target="_blank" rel="noreferrer"><span><strong>Open primary evidence ↗</strong><small>' + escapeHtml(row.source_system || 'source') + '</small></span><span>↗</span></a>' : '<div class="wb-source-link"><span><strong>No source URL</strong><small>Missing source link</small></span></div>';
    const capex = formatCapex(row);
    const capacity = formatCapacity(row);
    const stages = ['Demand','Customer','Constraint','CapEx','Build','Prod','Revenue','ROIC'];
    const active = new Set();
    if (row.demand_evidence || row.evidence) active.add('Demand');
    if (row.customer_commitment || row.customer) active.add('Customer');
    if (row.capacity_before != null || row.capacity_after != null) active.add('Constraint');
    if (row.capex && (row.capex.low != null || row.capex.high != null)) active.add('CapEx');
    if (/build|construction|facility|plant/i.test((row.status || '') + ' ' + (row.project_name || ''))) active.add('Build');
    if (row.production_start || /operational|production|realized|ramping/i.test(row.status || '')) active.add('Prod');
    const metrics = row.type === 'financial'
      ? metric('Value',formatFinancialValue(row)) + metric('Unit',escapeHtml(row.unit || '')) + metric('Value type',escapeHtml(row.value_type || '')) + metric('Period',escapeHtml(row.target_date || ''))
      : metric('CapEx',capex) + metric('Capacity',capacity) + metric('Status',row.status ? escapeHtml(row.status) : '') + metric('Target',escapeHtml(row.target_date || row.period_end || row.production_start || ''));
    const provenance =
      '<div class="wb-section"><h3>Provenance</h3>' + src +
      '<dl class="wb-kv"><dt>Value type</dt><dd>' + escapeHtml(row.value_type || row.event_type || 'record') + '</dd><dt>Quality</dt><dd>' + escapeHtml(row.quality || 'unknown') + '</dd><dt>Document</dt><dd>' + escapeHtml(row.source_doc_id || '—') + '</dd><dt>Imported via</dt><dd>' + escapeHtml(row.import_source || row.source_system || '—') + '</dd><dt>Imported at</dt><dd>' + escapeHtml(row.imported_at || '—') + '</dd><dt>Record ID</dt><dd>' + escapeHtml(row.import_record_id || row.id || '—') + '</dd></dl></div>';
    return '<div class="wb-inspector-head"><div class="wb-inspector-headline"><div><div class="eyebrow">' + escapeHtml(row.entity_id || row.type || 'record') + '</div><h2>' + escapeHtml(row.project_name || row.concept_id || row.company || row.name || row.id) + '</h2></div><button class="wb-close" type="button" data-close-inspector aria-label="Close inspector">×</button></div>' +
      '<div class="wb-tabs" role="tablist" aria-label="Inspector tabs"><button class="active" type="button" role="tab" data-inspector-tab="overview">Overview</button><button type="button" role="tab" data-inspector-tab="evidence">Evidence</button><button type="button" role="tab" data-inspector-tab="raw">Raw</button></div></div>' +
      '<div class="wb-inspector-body">' +
      '<section data-inspector-pane="overview">' +
      '<div class="wb-metric-grid">' + metrics + '</div>' +
      financialHistoryHtml(row) +
      '<div class="wb-stage">' + stages.map(s => '<span class="' + (active.has(s) ? 'on' : '') + '">' + s + '</span>').join('') + '</div>' +
      '<div class="wb-section"><h3>Company</h3><p><strong>' + escapeHtml(row.company || row.name || row.entity_id || '') + '</strong> · ' + escapeHtml(row.role || '') + (row.country ? ' · ' + escapeHtml(row.country) : '') + '</p></div>' +
      linkedWorkspaceHtml(row) +
      (row.product ? '<div class="wb-section"><h3>Product / Technology</h3><p>' + escapeHtml(row.product) + (row.technology ? ' · ' + escapeHtml(row.technology) : '') + '</p></div>' : '') +
      '</section>' +
      '<section data-inspector-pane="evidence" hidden>' +
      ((row.demand_evidence || row.evidence) ? '<div class="wb-section"><h3>Evidence</h3><p>' + escapeHtml(row.demand_evidence || row.evidence) + '</p></div>' : '<div class="wb-empty">No evidence text on this record.</div>') +
      provenance +
      '</section>' +
      '<section data-inspector-pane="raw" hidden><div class="wb-section"><h3>Raw record</h3><pre class="wb-raw-record">' + escapeHtml(JSON.stringify(row.raw || row,null,2)) + '</pre></div></section>' +
      '</div>';
  };

  const openInspector = id => {
    const row = rows.find(r => r.id === id);
    if (!row || !inspector || !workspace) return;
    workspaceApi.setActive(state,row);
    inspector.innerHTML = inspectorHtml(row);
    workspace.classList.add('has-inspector');
    q('[data-close-inspector]')?.addEventListener('click',closeInspector);
    qa('[data-inspector-tab]').forEach(btn=>btn.addEventListener('click',()=>applyInspectorTab(btn.getAttribute('data-inspector-tab'))));
    qa('[data-linked-route]').forEach(btn=>btn.addEventListener('click',()=>{
      const route=btn.getAttribute('data-linked-route') || '';
      const entity=btn.getAttribute('data-linked-entity') || '';
      location.href=(payload.base || '/') + route + '?q=' + encodeURIComponent(entity);
    }));
    applyInspectorTab(state.inspector.tab || 'overview');
    renderLinkedStrip();
    renderTable();
    writeUrl();
  };

  const closeInspector = () => {
    workspaceApi.clearActive(state);
    workspaceApi.setInspectorTab(state,'overview');
    workspace?.classList.remove('has-inspector');
    if (inspector) inspector.innerHTML = '';
    renderLinkedStrip();
    renderTable();
    writeUrl();
  };

  const toggleSelected = id => {
    workspaceApi.toggleSelected(state,id);
    renderCompare(); renderTable(); writeUrl();
  };

  const hydrateSelect = (key, values) => {
    const select = q('[data-filter="' + key + '"]');
    if (!select) return;
    const current = state[key];
    for (const value of values.filter(Boolean).sort((a,b)=>String(a).localeCompare(String(b),undefined,{numeric:true}))) {
      const opt = document.createElement('option');
      opt.value = value; opt.textContent = value;
      select.appendChild(opt);
    }
    select.value = current;
    select.addEventListener('change',() => { state[key] = select.value; renderTable(); writeUrl(); });
  };

  const toast = message => {
    const el = document.createElement('div');
    el.className = 'wb-toast'; el.textContent = message; document.body.appendChild(el);
    setTimeout(()=>el.remove(),1600);
  };

  const exportRows = subset => {
    const selectedRows = subset === 'selected' ? rows.filter(r=>state.selected.has(r.id)) : filteredRows();
    const exportCols = orderedColumns().filter(c=>c.key !== 'select' && state.visibleColumns.has(c.key));
    const csv = [
      exportCols.map(c=>c.label),
      ...selectedRows.map(row=>exportCols.map(c => {
        const value = c.key === 'capex' ? formatCapex(row).replace(/<[^>]+>/g,'') : cellValue(row,c.key);
        const plain = value == null ? '' : String(value);
        return '"' + plain.replaceAll('"','""') + '"';
      }))
    ].map(r=>r.join(',')).join('\n');
    const blob = new Blob([csv],{type:'text/csv;charset=utf-8'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='semiconductor-' + payload.view + '-' + subset + '.csv'; a.click(); URL.revokeObjectURL(a.href);
    toast('CSV exported: ' + selectedRows.length + ' rows');
  };

  const downloadText = (filename,text,type='application/json;charset=utf-8') => {
    const blob=new Blob([text],{type});
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob); a.download=filename; a.click(); URL.revokeObjectURL(a.href);
  };
  const exportJson = () => {
    const data=filteredRows().map(row=>row.raw || row);
    downloadText('semiconductor-' + payload.view + '-displayed.json',JSON.stringify(data,null,2));
    toast('Displayed JSON exported: ' + data.length + ' rows');
  };
  const exportMetadata = () => {
    const metadata={
      ...(payload.exportMeta || {}),
      source_api:payload.apiUrl,
      current_view:location.pathname + location.search,
      filters:{
        query:state.query,country:state.country,role:state.role,quality:state.quality,status:state.status,
        include:state.includeFilters,exclude:state.excludeFilters,sort:state.sortKey,dir:state.sortDir,
        visible_columns:[...state.visibleColumns],
      },
      displayed_row_count:filteredRows().length,
      exported_at:new Date().toISOString(),
    };
    downloadText('semiconductor-' + payload.view + '-metadata.json',JSON.stringify(metadata,null,2));
    toast('Metadata exported');
  };
  const copyApiUrl = async () => {
    const url=new URL(payload.apiUrl || '',location.origin).href;
    try{await navigator.clipboard.writeText(url);toast('Canonical API URL copied')}catch{toast('Copy failed')}
  };

  const chartValueText = value => {
    const n=Number(value);
    if(!Number.isFinite(n)) return String(value ?? '—');
    return Math.abs(n)>=1e9 ? (n/1e9).toFixed(1)+'B' : Math.abs(n)>=1e6 ? (n/1e6).toFixed(1)+'M' : n.toLocaleString(undefined,{maximumFractionDigits:2});
  };
  const chartMarkAttrs = point => 'data-chart-key="' + escapeHtml(point.filterKey || '') + '" data-chart-value="' + escapeHtml(point.filterValue || '') + '" data-chart-record="' + escapeHtml(point.recordId || '') + '"';
  const barChartHtml = model => {
    const max=Math.max(...model.data.map(d=>Math.abs(Number(d.value)||0)),1);
    return '<div class="wb-bar-chart">' + model.data.map((point,index)=>{
      const pct=Math.max(2,Math.abs(Number(point.value)||0)/max*100);
      return '<button type="button" class="wb-bar-row" ' + chartMarkAttrs(point) + '><span class="wb-bar-label">' + escapeHtml(point.label) + '</span><span class="wb-bar-track"><i style="width:' + pct.toFixed(2) + '%;--chart-index:' + (index%6) + '"></i></span><b>' + escapeHtml(chartValueText(point.value)) + '</b></button>';
    }).join('') + '</div>';
  };
  const lineChartHtml = model => {
    const data=model.data;
    if(!data.length) return '<div class="wb-empty">No line data.</div>';
    const values=data.map(d=>Number(d.value));
    const min=Math.min(...values),max=Math.max(...values),span=max-min||1;
    const w=560,h=120,p=12;
    const coords=data.map((d,i)=>({
      ...d,
      x:data.length===1?w/2:p+i*((w-p*2)/(data.length-1)),
      y:h-p-((Number(d.value)-min)/span)*(h-p*2),
    }));
    const points=coords.map(d=>d.x.toFixed(1)+','+d.y.toFixed(1)).join(' ');
    return '<svg class="wb-pastel-line" viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+escapeHtml(model.title)+'"><polyline points="'+points+'"></polyline>' +
      coords.map((d,index)=>'<circle tabindex="0" role="button" cx="'+d.x.toFixed(1)+'" cy="'+d.y.toFixed(1)+'" r="5" '+chartMarkAttrs(d)+' style="--chart-index:'+(index%6)+'"><title>'+escapeHtml(d.label+' '+chartValueText(d.value))+'</title></circle>').join('') +
      '</svg><div class="wb-chart-axis"><span>'+escapeHtml(data[0]?.label||'')+'</span><span>'+escapeHtml(data[data.length-1]?.label||'')+'</span></div>';
  };
  const pieChartHtml = model => {
    const total=model.data.reduce((sum,d)=>sum+Number(d.value||0),0)||1;
    let cursor=0;
    const palette=['var(--chart-0)','var(--chart-1)','var(--chart-2)','var(--chart-3)','var(--chart-4)','var(--chart-5)'];
    const stops=model.data.map((d,index)=>{
      const start=cursor;
      cursor+=Number(d.value||0)/total*100;
      return palette[index%palette.length]+' '+start.toFixed(2)+'% '+cursor.toFixed(2)+'%';
    }).join(',');
    return '<div class="wb-pie-layout"><div class="wb-pie" style="background:conic-gradient('+stops+')" role="img" aria-label="'+escapeHtml(model.title)+'"></div><div class="wb-pie-legend">' +
      model.data.map((d,index)=>'<button type="button" '+chartMarkAttrs(d)+'><i style="--chart-index:'+(index%6)+'"></i><span>'+escapeHtml(d.label)+'</span><b>'+escapeHtml(chartValueText(d.value))+'</b></button>').join('') +
      '</div></div>';
  };
  const renderChart = () => {
    if(!chartPanel) return;
    const activeRow=rows.find(r=>r.id===state.active.rowId) || null;
    const model=chartEngine.build({view:payload.view,rows:filteredRows(),activeRow,requestedType:state.analysis.chartType});
    const supported=['auto','bar','pie','line'];
    chartPanel.innerHTML='<div class="wb-chart-head"><div><strong>'+escapeHtml(model.title)+'</strong><small>'+escapeHtml(model.valueLabel || '')+'</small></div><div class="wb-chart-types">' +
      supported.map(type=>'<button type="button" data-chart-type="'+type+'" class="'+(state.analysis.chartType===type?'active':'')+'">'+type+'</button>').join('') +
      '</div></div><div class="wb-chart-body">' +
      (model.type==='bar'?barChartHtml(model):model.type==='line'?lineChartHtml(model):model.type==='pie'?pieChartHtml(model):'<div class="wb-empty">No chartable data for this screen.</div>') +
      '</div>';
    qa('[data-chart-type]').forEach(btn=>btn.addEventListener('click',()=>{
      state.analysis.chartType=btn.getAttribute('data-chart-type') || 'auto';
      renderChart();
    }));
    qa('[data-chart-key]').forEach(mark=>{
      const open=ev=>{ev.preventDefault();openChartMenu(mark,ev.clientX||window.innerWidth/2,ev.clientY||140)};
      mark.addEventListener('click',open);
      mark.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){open(ev)}});
    });
  };
  const openChartMenu = (mark,x,y) => {
    closeCellMenu();
    const key=mark.getAttribute('data-chart-key') || '';
    const value=mark.getAttribute('data-chart-value') || '';
    const recordId=mark.getAttribute('data-chart-record') || '';
    const menu=document.createElement('div');
    menu.className='wb-cell-menu';
    menu.style.left=Math.min(x,window.innerWidth-230)+'px';
    menu.style.top=Math.min(y,window.innerHeight-190)+'px';
    menu.innerHTML=
      (key&&value?'<button type="button" data-chart-action="include">Filter by <strong>'+escapeHtml(value)+'</strong></button><button type="button" data-chart-action="exclude">Exclude <strong>'+escapeHtml(value)+'</strong></button>':'') +
      '<button type="button" data-chart-action="underlying">View underlying record</button>';
    document.body.appendChild(menu);
    activeCellMenu=menu;
    menu.querySelector('[data-chart-action="include"]')?.addEventListener('click',()=>addCrossFilter('include',key,value));
    menu.querySelector('[data-chart-action="exclude"]')?.addEventListener('click',()=>addCrossFilter('exclude',key,value));
    menu.querySelector('[data-chart-action="underlying"]')?.addEventListener('click',()=>{
      closeCellMenu();
      let row=recordId ? rows.find(r=>r.id===recordId) : null;
      if(!row && key&&value) row=rows.find(r=>String(cellValue(r,key)??'')===value);
      if(!row) row=rows.find(r=>r.id===state.active.rowId) || null;
      if(row) openInspector(row.id); else toast('No underlying record in this slice');
    });
  };

  const getSavedViews = () => {
    try { return JSON.parse(localStorage.getItem('semicon:saved-views') || '{}'); }
    catch { return {}; }
  };
  const renderSavedViews = () => {
    if (!viewsBody) return;
    const base = payload.base || '/';
    const presets = [
      ['Primary source only', location.pathname + '?quality=primary_source_extracted'],
      ['Japan', location.pathname + '?country=Japan'],
      ['Capacity expansion', base + 'capacity/'],
      ['Financials', base + 'financials/'],
      ['Imported / unverified audit', base + 'quality/?quality=imported_unverified'],
      ['Canonical activity', base + 'activity/'],
    ];
    const all = getSavedViews();
    const entries = Object.entries(all).sort((a,b)=>String(b[1]?.saved_at||'').localeCompare(String(a[1]?.saved_at||'')));
    viewsBody.innerHTML =
      '<div class="wb-saved-group"><h3>Built-in screens</h3>' +
      presets.map(([name,url])=>'<button class="wb-preset-link" type="button" data-preset-url="' + escapeHtml(url) + '"><strong>' + escapeHtml(name) + '</strong><small>' + escapeHtml(url) + '</small></button>').join('') +
      '</div><div class="wb-saved-group"><h3>Saved views</h3>' +
      (entries.length ? entries.map(([name,item]) =>
        '<div class="wb-saved-row"><button type="button" data-load-view="' + escapeHtml(name) + '"><span><strong>' + escapeHtml(name) + '</strong><small>' + escapeHtml(item.url || '') + '</small></span><small>' + escapeHtml((item.saved_at || '').slice(0,19).replace('T',' ')) + '</small></button><button type="button" class="danger" data-delete-view="' + escapeHtml(name) + '">Delete</button></div>'
      ).join('') : '<div class="wb-empty">No saved views yet.</div>') + '</div>';
    [...viewsBody.querySelectorAll('[data-preset-url]')].forEach(btn=>btn.addEventListener('click',()=>{ location.href=btn.getAttribute('data-preset-url') || location.pathname; }));
    [...viewsBody.querySelectorAll('[data-load-view]')].forEach(btn=>btn.addEventListener('click',()=>{
      const allNow=getSavedViews(); const item=allNow[btn.getAttribute('data-load-view')];
      if(item?.url) location.href=item.url;
    }));
    [...viewsBody.querySelectorAll('[data-delete-view]')].forEach(btn=>btn.addEventListener('click',()=>{
      const allNow=getSavedViews(); const name=btn.getAttribute('data-delete-view'); delete allNow[name];
      localStorage.setItem('semicon:saved-views',JSON.stringify(allNow)); renderSavedViews(); toast('Deleted view: ' + name);
    }));
  };
  const saveView = () => {
    const name = prompt('Saved View name');
    if (!name) return;
    const data = {url:location.pathname + location.search, saved_at:new Date().toISOString()};
    const all = getSavedViews();
    all[name] = data;
    localStorage.setItem('semicon:saved-views',JSON.stringify(all));
    renderSavedViews();
    toast('Saved view: ' + name);
  };

  const copyView = async () => {
    try { await navigator.clipboard.writeText(location.href); toast('View URL copied'); }
    catch { toast('Copy failed'); }
  };

  const renderCommand = needle => {
    if (!commandResults) return;
    const n=(needle||'').toLowerCase();
    const candidates = rows.filter(r=>!n || [r.company,r.name,r.ticker,r.project_name,r.entity_id,r.id].filter(Boolean).join(' ').toLowerCase().includes(n)).slice(0,12);
    commandResults.innerHTML = candidates.map(r=>'<button class="wb-command-item" type="button" data-command-row="' + escapeHtml(r.id) + '"><span><strong>' + escapeHtml(r.project_name || r.company || r.name || r.id) + '</strong><small>' + escapeHtml(r.company && r.project_name ? r.company : r.entity_id || '') + '</small></span><small>Open ↵</small></button>').join('');
    [...commandResults.querySelectorAll('[data-command-row]')].forEach(btn=>btn.addEventListener('click',()=>{ command.close(); openInspector(btn.getAttribute('data-command-row')); }));
  };

  loadTableLayout();
  readUrl();
  hydrateSelect('country',[...new Set(rows.map(r=>r.country))]);
  hydrateSelect('role',[...new Set(rows.map(r=>r.role))]);
  hydrateSelect('quality',[...new Set(rows.map(r=>r.quality))]);
  hydrateSelect('status',[...new Set(rows.map(r=>r.status))]);

  searchInput?.addEventListener('input',()=>{ state.query=searchInput.value; renderTable(); writeUrl(); });
  qa('[data-sort]').forEach(th=>th.addEventListener('click',()=>{
    const key=th.getAttribute('data-sort');
    if(state.sortKey===key) state.sortDir=state.sortDir==='asc'?'desc':'asc'; else {state.sortKey=key;state.sortDir='asc'}
    renderTable(); writeUrl();
  }));
  q('[data-clear-filters]')?.addEventListener('click',()=>{
    state.query='';state.country='';state.role='';state.quality='';state.status='';
    if(searchInput)searchInput.value='';
    for(const key of ['country','role','quality','status']){const el=q('[data-filter="'+key+'"]');if(el)el.value=''}
    renderTable();writeUrl();
  });
  q('[data-open-mobile-nav]')?.addEventListener('click',()=>mobileNavDialog?.showModal());
  q('[data-close-mobile-nav]')?.addEventListener('click',()=>mobileNavDialog?.close());
  q('[data-open-export]')?.addEventListener('click',()=>exportDialog?.showModal());
  q('[data-close-export]')?.addEventListener('click',()=>exportDialog?.close());
  q('[data-save-view]')?.addEventListener('click',saveView);
  q('[data-open-views]')?.addEventListener('click',()=>{renderSavedViews();viewsDialog?.showModal()});
  q('[data-close-views]')?.addEventListener('click',()=>viewsDialog?.close());
  qa('[data-copy-view]').forEach(btn=>btn.addEventListener('click',copyView));
  q('[data-open-columns]')?.addEventListener('click',()=>{renderColumnDialog();columnDialog?.showModal()});
  q('[data-close-columns]')?.addEventListener('click',()=>columnDialog?.close());
  q('[data-open-compare]')?.addEventListener('click',openCompare);
  q('[data-close-compare]')?.addEventListener('click',()=>compareDialog?.close());
  q('[data-export-visible]')?.addEventListener('click',()=>exportRows('visible'));
  qa('[data-export-selected]').forEach(btn=>btn.addEventListener('click',()=>exportRows('selected')));
  q('[data-export-json]')?.addEventListener('click',exportJson);
  q('[data-export-meta]')?.addEventListener('click',exportMetadata);
  q('[data-copy-api]')?.addEventListener('click',copyApiUrl);
  q('[data-clear-selection]')?.addEventListener('click',()=>{state.selected.clear();renderCompare();renderTable();writeUrl()});
  q('[data-open-command]')?.addEventListener('click',()=>{renderCommand('');command?.showModal();commandInput?.focus()});
  commandInput?.addEventListener('input',()=>renderCommand(commandInput.value));
  command?.addEventListener('click',ev=>{if(ev.target===command)command.close()});
  columnDialog?.addEventListener('click',ev=>{if(ev.target===columnDialog)columnDialog.close()});
  compareDialog?.addEventListener('click',ev=>{if(ev.target===compareDialog)compareDialog.close()});
  viewsDialog?.addEventListener('click',ev=>{if(ev.target===viewsDialog)viewsDialog.close()});
  exportDialog?.addEventListener('click',ev=>{if(ev.target===exportDialog)exportDialog.close()});
  mobileNavDialog?.addEventListener('click',ev=>{if(ev.target===mobileNavDialog)mobileNavDialog.close()});
  let virtualScrollFrame = 0;
  tableWrap?.addEventListener('scroll',()=>{
    if (tableWrap.dataset.virtualized !== 'true') return;
    if (virtualScrollFrame) cancelAnimationFrame(virtualScrollFrame);
    virtualScrollFrame = requestAnimationFrame(()=>{ virtualScrollFrame=0; renderTable(); });
  },{passive:true});
  document.addEventListener('click',ev=>{if(activeCellMenu && !ev.target.closest('.wb-cell-menu')) closeCellMenu()});
  window.addEventListener('scroll',closeCellMenu,true);
  window.addEventListener('resize',closeCellMenu);
  document.addEventListener('keydown',ev=>{
    const target=ev.target;
    const typing=target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable;
    if((ev.metaKey||ev.ctrlKey)&&ev.key.toLowerCase()==='k'){ev.preventDefault();renderCommand('');command?.showModal();commandInput?.focus();return}
    if(ev.key==='/'&&!typing){ev.preventDefault();searchInput?.focus();return}
    if(ev.key==='Escape'&&state.activeId){closeInspector();return}
  });

  state.subscribe((_,type)=>{ if(type==='active'){renderLinkedStrip();renderChart()} });
  renderColumnDialog(); renderSavedViews(); renderSortState(); renderTable(); renderCompare(); renderLinkedStrip();
  if(state.activeId) openInspector(state.activeId);
})();
