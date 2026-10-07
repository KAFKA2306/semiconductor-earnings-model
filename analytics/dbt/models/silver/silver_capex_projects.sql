select
    *,
    'silver' as data_layer
from read_ndjson('{{ var("repo_root") }}/data/canonical/capex_projects.jsonl')
