select
    entity_id,
    count(*) as project_count,
    count(*) filter (
        where capex_plan_low is not null or capex_plan_high is not null
    ) as disclosed_capex_project_count,
    count(*) filter (
        where capacity_before is not null or capacity_after is not null
    ) as capacity_project_count,
    count(distinct source_doc_id) as source_document_count,
    max(announcement_date) as latest_announcement_date,
    'gold' as data_layer
from {{ ref('gold_capex_projects') }}
group by entity_id
