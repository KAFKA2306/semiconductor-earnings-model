export const classifyCanonicalChange = (row = {}) => {
  const text=[row.event_type,row.status,row.project_name,row.evidence].filter(Boolean).join(' ').toLowerCase();
  if(/guidance|forecast|outlook/.test(text)) return 'new_guidance';
  if(/commitment|agreement|lta|customer/.test(text)) return 'customer_commitment';
  if(/capacity|wafer|production capacity/.test(text)) return 'capacity_change';
  if(/facility|fab|plant|site/.test(text)) return 'facility_change';
  if(/stale|refresh|supersed/.test(text)) return 'source_refresh';
  if(/conflict|reject/.test(text)) return 'quality_change';
  if(/project|construction|build|ramp|production/.test(text)) return 'project_update';
  return 'disclosure_update';
};
