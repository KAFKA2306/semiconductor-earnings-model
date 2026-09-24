# Semiconductor Research Workbench capability parity audit

Date: 2026-09-23

This audit compares interaction capabilities, not visual imitation. The product criterion is whether a semiconductor-research workflow can move from screen → active context → underlying canonical record → provenance/source with fewer context switches.

## Reference capabilities

| Reference | Official capability used as benchmark | Workbench implementation | Remaining gap |
| --- | --- | --- | --- |
| Koyfin | Equity screener with 5,900+ filters; reusable watchlist views; custom dashboards; graph/table financial review | Screener filters, persistent watchlist, Saved Workspace, linked chart/grid/inspector context, financial history table + chart | No arbitrary user formulas; no free-form multi-widget drag grid |
| TradingView | Saved screens preserve filters/columns/sort/view; watchlist scanning; screener export; multi-select | URL state, Saved Workspace, reusable columns, persistent Shift-click multi-sort, watchlist filter, CSV/JSON export, Shift/Ctrl-style selection semantics | No undo/redo screen history; no market-price charting |
| Fiscal.ai | Company financial pages, charting, screener, standardized/as-reported financials with source traceability | Financials view, period history chart/table, value-type separation, source URL/provenance, canonical record/raw view | Financial universe is narrower and semiconductor-focused; no general-purpose AI research surface |
| Metabase | Chart/table drill-through to filter or underlying records; cross-filter behavior | Cell context actions and chart-mark Filter / Exclude / Underlying; linked ACTIVE state propagates across contexts | No drag-range chart filtering; fewer aggregation builders |
| Our World in Data Grapher | Displayed/full data downloads, metadata, data API, chart/table/map modes | Displayed/selected/full canonical exports, metadata JSON, canonical API link, chart/table views | No map mode for geographic datasets |

## Official references

- Koyfin features: https://www.koyfin.com/features/
- Koyfin screener: https://www.koyfin.com/features/stock-screener/
- Koyfin watchlists: https://www.koyfin.com/features/watchlists/
- Koyfin custom dashboards: https://www.koyfin.com/features/custom-dashboards/
- TradingView screener filters: https://www.tradingview.com/support/solutions/43000718745-how-to-use-filters-in-screener/
- TradingView saved screens: https://www.tradingview.com/support/solutions/43000718804-how-to-create-save-and-update-a-custom-screen/
- TradingView screener export: https://www.tradingview.com/support/solutions/43000474432-how-to-export-screener-data/
- TradingView screener → watchlist: https://www.tradingview.com/support/solutions/43000473930-how-to-add-the-screener-search-results-to-the-watchlist/
- Fiscal.ai API financials/source traceability: https://docs.fiscal.ai/docs/api-reference
- Fiscal.ai skills/screener: https://docs.fiscal.ai/docs/guides/mcp-skills
- Metabase drill-through: https://www.metabase.com/docs/latest/questions/visualizations/drill-through
- OWID Grapher example with displayed/full download + API: https://ourworldindata.org/grapher/population-with-un-projections?overlay=download-data

## Workbench-specific differentiator

The Workbench keeps semiconductor project/capacity/evidence records and financial observations connected to source-level provenance. ACTIVE selection is separate from compare SELECTED and dataset FILTER state. The same active record drives linked project, financial, facility, evidence, commitment, chart, lifecycle, and inspector context without turning selection into an implicit filter.

## Acceptance evidence

CI must provide:

- 1440×900 screenshot with active linked context
- 1366×768 screenshot with active linked context
- 390×844 grid screenshot
- 390×844 inspector screenshot
- 500-row filter/sort p95 ≤ 150 ms
- ACTIVE → linked-context p95 ≤ 100 ms
- keyboard row navigation, Enter/open, Space/select, Shift+Space range select, Escape/close, / search, Cmd/Ctrl+K command palette
- Shift+click multi-sort with visible priority and URL persistence
- no global pastel-watercolor stylesheet injection into Workbench or auxiliary research pages

The screenshot artifact is produced by the `Validate semiconductor BI workbench` workflow as `workbench-visual-evidence-<sha>`.


## JavaScript artifact size record

Measured from repository UTF-8 asset bytes before and after this workline:

| State | Assets | Bytes |
| --- | --- | ---: |
| Baseline `main` | `bi-workbench.js` | 39,895 |
| Hardened stacked branch | `bi-workbench.js` + `workspace-state.js` + `chart-engine.js` + `workbench-data-engine.js` | 76,532 |

The increase is explicit rather than hidden: state authority, deterministic chart/data engines, saved workspace/watchlist, keyboard handling, and runtime performance diagnostics were split into reusable assets. The performance gate is therefore based on measured interaction latency, not bundle size alone.
