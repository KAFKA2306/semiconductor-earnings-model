select
    *,
    'silver' as data_layer
from read_ndjson('{{ var("repo_root") }}/data/canonical/customer_commitments.jsonl')
