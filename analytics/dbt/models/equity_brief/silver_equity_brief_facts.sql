{{ config(materialized='view', enabled=var('equity_brief_facts', '') != '') }}

select
    id,
    cast(value as decimal(28, 6)) as value,
    kind,
    period,
    unit,
    evidence_id
from read_json_auto('{{ var("equity_brief_facts", "") | replace("'", "''") }}')
