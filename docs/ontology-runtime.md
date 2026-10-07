# Ontology Runtime v0.3

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

canonical sourceはread-onlyのまま維持し、Actionは`data/ontology_runtime/action_state.json`
へのoverlay-only mutationとして実行する。`action_log.jsonl` はhash chainを持ち、
idempotency key、expected_version、actor、before/afterを記録する。

## Compile and validate

```bash
uv run python scripts/check_ontology_runtime.py
uv run python -m pytest tests/test_ontology_runtime.py tests/test_ontology_actions.py -q
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
6. Actionはcanonical sourceへ直接書かず、overlay-onlyで実行する。
7. 全writeはidempotency keyとexpected_versionを必須にする。
8. rollbackも新しいAction Log recordとして残し、履歴を消さない。

## Controlled actions

有効化は明示的に行う。

```bash
export ONTOLOGY_ACTIONS_ENABLED=1
export ONTOLOGY_ACTION_ACTOR=kafka-local
export ONTOLOGY_ACTION_ROLE=operator
export ONTOLOGY_ACTION_TOKEN='replace-with-secret'
```

状態確認:

```bash
uv run python -m src.data_platform_cli get_ontology_action_status
```

dry-run:

```bash
uv run python -m src.data_platform_cli execute_ontology_action '{"action_type":"supersedeObservation","object_type":"Observation","primary_key":"micron:2026-05-28:eps_diluted:consolidated:actual:gaap","parameters":{"replacement_observation_id":"micron:2026-05-28:eps_diluted:consolidated:actual:non_gaap"},"idempotency_key":"example-001","expected_version":0,"dry_run":true}'
```

本実行では`dry_run:false`にする。戻す場合は実行結果の`action_id`と現在のversionを使う。

```bash
uv run python -m src.data_platform_cli rollback_ontology_action '{"action_id":"action:...","idempotency_key":"rollback-example-001","expected_version":1}'
```

REST POSTは`Authorization: Bearer $ONTOLOGY_ACTION_TOKEN`を必須とする。
MCP/CLI actionは既定でlocalhost/process-local運用とし、上記environment gateが未設定ならfail-closeする。

## Practical graph queries

MCP:

```text
search_ontology_objects(object_type="Issuer", query="Micron", limit=10)
get_ontology_object(object_type="Observation", primary_key="micron:2026-05-28:revenue:consolidated:actual")
get_ontology_neighbors(object_type="Observation", primary_key="micron:2026-05-28:revenue:consolidated:actual")
```

REST:

```text
GET /api/data-platform/v1/ontology/objects?type=Issuer&q=Micron&limit=10
GET /api/data-platform/v1/ontology/objects/Observation/micron:2026-05-28:revenue:consolidated:actual
GET /api/data-platform/v1/ontology/objects/Observation/micron:2026-05-28:revenue:consolidated:actual/neighbors
```

CLI:

```bash
uv run python -m src.data_platform_cli search_ontology_objects '{"object_type":"Issuer","query":"Micron","limit":10}'
uv run python -m src.data_platform_cli get_ontology_neighbors '{"object_type":"Observation","primary_key":"micron:2026-05-28:revenue:consolidated:actual"}'
```

Observationから `observationSubject` / `observationConcept` / `observationSource` / `disclosedIn`
を辿ることで、企業、意味、出典、文書へ戻れます。
