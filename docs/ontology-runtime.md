# Ontology Runtime v0.1

このrepositoryのOntologyは、特定の会社・指標を固定テーブルとして扱うだけでなく、
Object Type / Property / Link Type / Action Type / Interfaceを定義できる上位契約として運用する。

## Authority

- `ontology/semiconductor.ontology.json`: Ontology定義の正本
- `ontology/ontology-definition.schema.json`: 定義ファイル自体のJSON Schema
- `data/primary/entities.json`: Issuer / Security projectionの入力
- `data/financial_db/metric_catalog.json`: NormalizedConcept projectionの入力
- `src/ontology_runtime.py`: fail-closed compiler / projection runtime
- 生成されたObject / Linkは派生Viewであり、入力データを上書きしない

## Current primitives

- Object Types: Issuer, Security, NormalizedConcept, Observation, Source, Document, Evaluation, Claim
- Link Types: issuedBy, observationSubject, observationConcept, observationSource, disclosedIn, supportedBy
- Interfaces: Identified, Sourced, Temporal
- Action Types: supersedeObservation, setEvaluationStatus

Action TypeはOntology契約として定義するが、現在のData Platformはread-onlyのため
`executable: false` を必須とする。Authorization、Action Log、write auditが実装されるまで
runtimeから書き込みは行わない。

## Compile and validate

```bash
uv run python scripts/check_ontology_runtime.py
uv run python -m pytest tests/test_ontology_runtime.py -q
uv run --with "jsonschema>=4,<5" python -m jsonschema \
  -i ontology/semiconductor.ontology.json \
  ontology/ontology-definition.schema.json
```

CIではOntology定義、実データprojection、参照整合性、MCP/REST/CLI parityをfail-closeで検証する。

## Read interfaces

CLI:

```bash
uv run python -m src.data_platform_cli get_ontology_definition
uv run python -m src.data_platform_cli get_ontology_snapshot
```

REST:

```text
GET /api/data-platform/v1/ontology
GET /api/data-platform/v1/ontology/snapshot
```

MCP:

```text
get_ontology_definition
get_ontology_snapshot
```

`get_ontology_snapshot` は現在、実repositoryのCompany registryとmetric catalogから
Issuer / Security / NormalizedConcept ObjectとissuedBy Linkを決定論的に生成する。
definition hashと全入力hashを返すため、どのOntologyと入力から生成されたか逆引きできる。

## Evolution rules

1. Stable IDを再利用して別の意味へ変更しない。
2. Property削除・型変更・Link cardinality変更は破壊的変更として扱う。
3. NULLを既定値へ変換しない。
4. ObservationやDocumentを追加する場合、Source / provenanceを失わない。
5. 生成Viewをcanonical sourceへ昇格させない。
6. Actionを実行可能にする前にAuthorization、Action Log、idempotency、rollbackを実装する。

## Next runtime slice

次の実装対象はObservation / Source / Documentを既存financial-database v3からprojectし、
Observation -> Issuer / NormalizedConcept / Source / DocumentのLinkを実データ化すること。
