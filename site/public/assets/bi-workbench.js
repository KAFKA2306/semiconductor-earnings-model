(() => {
  const root = document.querySelector('[data-workbench]');
  if (!root) return;

  const payloadEl = document.getElementById('workbench-data');
  const payload = payloadEl ? JSON.parse(payloadEl.textContent || '{}') : {};
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  const columns = Array.isArray(payload.columns) ? payload.columns : [];
  const state = {
    query: '',
    country: '',
    role: '',
    quality: '',
    status: '',
    sortKey: payload.defaultSort || '',
    sortDir: 'asc',
    selected: new Set(),
    activeId: null,
    visibleColumns: new Set(columns.map(c => c.key)),
  };

  const q = sel => root.querySelector(sel);
  const qa = sel => [...root.querySelectorAll(sel)];
  const tableBody = q('[data-table-body]');
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
    state.sortDir = params.get('dir') === 'desc' ? 'desc' : 'asc';
    state.activeId = params.get('row') || null;
    const selected = (params.get('compare') || '').split(',').filter(Boolean);
    state.selected = new Set(selected);
    const cols = (params.get('cols') || '').split(',').filter(Boolean);
    if (cols.length) state.visibleColumns = new Set(cols.filter(key => columns.some(c => c.key === key)));
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

  const renderTable = () => {
    qa('[data-col]').forEach(th => th.classList.toggle('wb-hidden', !state.visibleColumns.has(th.getAttribute('data-col'))));
    const visible = filteredRows();
    if (resultCount) resultCount.textContent = visible.length.toLocaleString();
    if (!tableBody) return;
    if (!visible.length) {
      tableBody.innerHTML = '<tr><td colspan="' + columns.length + '"><div class="wb-empty">No rows match the current screen.</div></td></tr>';
      return;
    }
    tableBody.innerHTML = visible.map(row => {
      const selected = state.activeId === row.id ? ' selected' : '';
      return '<tr class="' + selected.trim() + '" data-row="' + escapeHtml(row.id) + '" tabindex="0">' +
        columns.filter(c => state.visibleColumns.has(c.key)).map(col => '<td class="' + (col.numeric ? 'num' : '') + '">' + cellHtml(row,col) + '</td>').join('') +
        '</tr>';
    }).join('');
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
  };

  const renderColumnDialog = () => {
    if (!columnList) return;
    columnList.innerHTML = columns.map(col => {
      const locked = col.key === 'select' || col.key === 'company';
      return '<label class="wb-column-item"><input type="checkbox" data-column-toggle="' + escapeHtml(col.key) + '"' +
        (state.visibleColumns.has(col.key) ? ' checked' : '') + (locked ? ' disabled' : '') + '><span>' + escapeHtml(col.label || col.key) + '</span></label>';
    }).join('');
    [...columnList.querySelectorAll('[data-column-toggle]')].forEach(input => input.addEventListener('change',() => {
      const key=input.getAttribute('data-column-toggle');
      if(input.checked) state.visibleColumns.add(key); else state.visibleColumns.delete(key);
      state.visibleColumns.add('select'); state.visibleColumns.add('company');
      renderTable(); writeUrl();
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
    const compareCols = columns.filter(c => !['select','company'].includes(c.key) && state.visibleColumns.has(c.key));
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
    return '<div class="wb-inspector-head"><div class="wb-inspector-headline"><div><div class="eyebrow">' + escapeHtml(row.entity_id || row.type || 'record') + '</div><h2>' + escapeHtml(row.project_name || row.company || row.name || row.id) + '</h2></div><button class="wb-close" type="button" data-close-inspector aria-label="Close inspector">×</button></div>' +
      '<div class="wb-tabs"><button class="active" type="button">Overview</button><button type="button" data-tab-evidence>Evidence</button><button type="button" data-tab-raw>Raw</button></div></div>' +
      '<div class="wb-inspector-body">' +
      '<div class="wb-metric-grid">' +
      metric('CapEx',capex) + metric('Capacity',capacity) +
      metric('Status',row.status ? escapeHtml(row.status) : '') + metric('Target',escapeHtml(row.target_date || row.period_end || row.production_start || '')) +
      '</div>' +
      '<div class="wb-stage">' + stages.map(s => '<span class="' + (active.has(s) ? 'on' : '') + '">' + s + '</span>').join('') + '</div>' +
      '<div class="wb-section"><h3>Company</h3><p><strong>' + escapeHtml(row.company || row.name || row.entity_id || '') + '</strong> · ' + escapeHtml(row.role || '') + (row.country ? ' · ' + escapeHtml(row.country) : '') + '</p></div>' +
      (row.product ? '<div class="wb-section"><h3>Product / Technology</h3><p>' + escapeHtml(row.product) + (row.technology ? ' · ' + escapeHtml(row.technology) : '') + '</p></div>' : '') +
      ((row.demand_evidence || row.evidence) ? '<div class="wb-section"><h3>Evidence</h3><p>' + escapeHtml(row.demand_evidence || row.evidence) + '</p></div>' : '') +
      '<div class="wb-section"><h3>Provenance</h3>' + src +
      '<dl class="wb-kv"><dt>Value type</dt><dd>' + escapeHtml(row.value_type || row.event_type || 'record') + '</dd><dt>Quality</dt><dd>' + escapeHtml(row.quality || 'unknown') + '</dd><dt>Document</dt><dd>' + escapeHtml(row.source_doc_id || '—') + '</dd><dt>Imported via</dt><dd>' + escapeHtml(row.import_source || row.source_system || '—') + '</dd><dt>Imported at</dt><dd>' + escapeHtml(row.imported_at || '—') + '</dd><dt>Record ID</dt><dd>' + escapeHtml(row.import_record_id || row.id || '—') + '</dd></dl></div>' +
      '<div class="wb-section"><h3>Raw record</h3><pre style="white-space:pre-wrap;overflow-wrap:anywhere;font:10px/1.5 ui-monospace,monospace;background:#f9fafb;border:1px solid #eaecf0;padding:8px">' + escapeHtml(JSON.stringify(row.raw || row,null,2)) + '</pre></div>' +
      '</div>';
  };

  const openInspector = id => {
    const row = rows.find(r => r.id === id);
    if (!row || !inspector || !workspace) return;
    state.activeId = id;
    inspector.innerHTML = inspectorHtml(row);
    workspace.classList.add('has-inspector');
    q('[data-close-inspector]')?.addEventListener('click',closeInspector);
    renderTable();
    writeUrl();
  };

  const closeInspector = () => {
    state.activeId = null;
    workspace?.classList.remove('has-inspector');
    if (inspector) inspector.innerHTML = '';
    renderTable();
    writeUrl();
  };

  const toggleSelected = id => {
    if (state.selected.has(id)) state.selected.delete(id); else state.selected.add(id);
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
    const exportCols = columns.filter(c=>c.key !== 'select' && state.visibleColumns.has(c.key));
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

  const saveView = () => {
    const name = prompt('Saved View name');
    if (!name) return;
    const data = {url:location.pathname + location.search, saved_at:new Date().toISOString()};
    const all = JSON.parse(localStorage.getItem('semicon:saved-views') || '{}');
    all[name] = data;
    localStorage.setItem('semicon:saved-views',JSON.stringify(all));
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
  q('[data-save-view]')?.addEventListener('click',saveView);
  qa('[data-copy-view]').forEach(btn=>btn.addEventListener('click',copyView));
  q('[data-open-columns]')?.addEventListener('click',()=>{renderColumnDialog();columnDialog?.showModal()});
  q('[data-close-columns]')?.addEventListener('click',()=>columnDialog?.close());
  q('[data-open-compare]')?.addEventListener('click',openCompare);
  q('[data-close-compare]')?.addEventListener('click',()=>compareDialog?.close());
  q('[data-export-visible]')?.addEventListener('click',()=>exportRows('visible'));
  q('[data-export-selected]')?.addEventListener('click',()=>exportRows('selected'));
  q('[data-clear-selection]')?.addEventListener('click',()=>{state.selected.clear();renderCompare();renderTable();writeUrl()});
  q('[data-open-command]')?.addEventListener('click',()=>{renderCommand('');command?.showModal();commandInput?.focus()});
  commandInput?.addEventListener('input',()=>renderCommand(commandInput.value));
  command?.addEventListener('click',ev=>{if(ev.target===command)command.close()});
  columnDialog?.addEventListener('click',ev=>{if(ev.target===columnDialog)columnDialog.close()});
  compareDialog?.addEventListener('click',ev=>{if(ev.target===compareDialog)compareDialog.close()});
  document.addEventListener('keydown',ev=>{
    if((ev.metaKey||ev.ctrlKey)&&ev.key.toLowerCase()==='k'){ev.preventDefault();renderCommand('');command?.showModal();commandInput?.focus()}
    if(ev.key==='Escape'&&state.activeId)closeInspector();
  });

  renderColumnDialog(); renderTable(); renderCompare();
  if(state.activeId) openInspector(state.activeId);
})();
