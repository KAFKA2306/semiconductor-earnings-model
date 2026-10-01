# Analytical Star Schema + Foundry-style Ontology

## Architecture

The repository now treats canonical evidence, analytical storage, and semantic operations as separate contracts.

```text
Primary disclosures / canonical ledgers
                |
                v
      Financial Database v3
                |
        +-------+-------+
        |               |
        v               v
  Star Schema      Foundry-style Ontology
  analytics        objects / links / actions
        |               |
        +-------+-------+
                |
                v
          API / UI / agents
```

Neither the Star Schema nor the Ontology is the source of truth. Both are deterministic projections of evidence-bearing canonical data.

## Why both

The Star Schema is optimized for repeated aggregation, comparison, BI queries, and joins.

The Ontology is optimized for semantic identity, relationships, navigation, governed actions, and agent-facing operations.

Trying to force both jobs into one representation creates either an awkward warehouse or an awkward knowledge graph.

## Public analytical contract

Generated artifact:

- `/api/v3/financial-database/star-schema.json`
- Star tables are also materialized inside `/api/v3/financial-database/financial.db`.

### Dimensions

| Dimension | Grain |
|---|---|
| `dim_company` | one issuer |
| `dim_metric` | one normalized or derived metric |
| `dim_period` | one reporting-period identity |
| `dim_source` | one evidence source |
| `dim_value_type` | one semantic value class |
| `dim_scope` | one consolidated/segment/geography scope |
| `dim_rule` | one explicit evaluation rule |

### Facts

| Fact | Grain |
|---|---|
| `fact_observation` | one source-traceable semantic observation |
| `fact_derived_metric` | one formula-backed metric for one issuer and period |
| `fact_evaluation` | one rule evaluation for one issuer |
| `fact_evidence_edge` | one lineage edge |

The projection uses deterministic hash-based surrogate integer keys. Natural identifiers remain in every dimension and fact so data can always be traced back to canonical records.

## Semantic boundaries

Actuals, company guidance, analyst consensus, internal estimates, scenarios, and market observations are separate members of `dim_value_type`. They are never merged into one undifferentiated measure.

Period, source, scope, and metric identity are explicit foreign keys. A fact cannot be materialized when its required dimensions do not resolve.

## Relationship to the Ontology

The existing Foundry-style Ontology remains the semantic and governed-operation layer:

- Object Types
- Properties
- Link Types
- Action Types
- Interfaces

The Star Schema does not replace those concepts. It provides a stable analytical projection for BI and quantitative workloads, while the Ontology provides meaning and graph navigation.

## Fail-closed validation

`scripts/build_star_schema.py` fails when:

- the source financial schema version is unexpected
- an observation references an unresolved company, metric, source, or value type
- a derived metric or evaluation references an unresolved dimension
- a deterministic surrogate-key collision is detected
- fact counts do not match their source collections
- SQLite foreign-key or integrity checks fail

`tests/test_star_schema.py` additionally verifies JSON/SQLite parity and a full observation-to-dimension join.
