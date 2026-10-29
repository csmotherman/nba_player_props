# NBA Player Props — data foundation

Point-in-time NBA data warehouse and feature infrastructure for player-prop research. **No prediction model exists yet**; this repository
is the audited foundation (data, features, leakage controls, evidence) that a model will be built and evaluated on.

| Doc | What it is |
|---|---|
| `NBA_DATA_BLUEPRINT.md` | Architecture, availability, methodology, QC, hypotheses |
| `NBA_DATA_QUALITY_REPORT.md` | Quantitative warehouse report (generated from queries) |
| `NBA_DATA_GAPS.md` | Missing data, external sources, open tests |
| `NBA_FEATURE_CATALOG.csv` / `nba_feature_registry.json` | 239-feature registry with readiness, implementation status and six-level verification |
| `NBA_FEATURE_READINESS.csv` | Priority vs executability vs implementation, per feature |
| `NBA_FEATURE_DEPENDENCIES.md`, `NBA_API_ENDPOINT_INVENTORY.csv`, `nba_feature_explorer.html` | Generated from the registry / discovery evidence |

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m nba_props ingest --season 2025-26                  # schedule + game logs + advanced (≈7 requests per season)
python -m nba_props ingest --season 2026-27 --incremental    # refetch the in-progress season
python -m nba_props boxscores --season 2025-26 --max-games 100   # starters/inactives per game (≈1 request each; resumable)
python -m nba_props validate                                  # data-quality checks -> data_quality_results
python -m nba_props features --season 2025-26                 # point-in-time feature tables for cutoffs 24h / 6h / 1h
python -m nba_props status
python -m nba_props report                                    # writes NBA_DATA_QUALITY_REPORT.md
python -m nba_props tracking-pilot                            # OPTIONAL isolated tracking-window pilot
```

Ingestion is idempotent and resumable: completed requests are replayed from `data/raw/` (content-addressed, append-only) without network access,
and per-game collection commits in small batches. The stats API is unofficial and throttles bursts; defaults are deliberately slow
(1.5 s between requests, 1 worker, circuit breaker). Do not raise them for backfills.

## Tests

```bash
pytest                          # offline, deterministic (real-data fixtures under tests/fixtures; no network, no warehouse needed)
NBA_PROPS_LIVE=1 pytest -m integration       # few live API calls
pytest -m realdata              # against the local warehouse
python scripts/run_formula_checks.py && python scripts/run_leakage_audit.py   # real-data evidence -> data/discovery/*.json
python scripts/build_artifacts.py            # validate + regenerate registry artifacts (deterministic)
```

## Layout

```
nba_props/   api/ (client, guards)  ingestion/  storage/ (DuckDB DDL, upserts)  features/ (as-of engine)  validation/ (quality, formulas, audit, timetravel, report)  tracking/ (optional pilot)
scripts/     registry/ (authoritative feature definitions, validator, readiness)  discovery + QC scripts  build_artifacts.py  make_fixtures.py
tests/       unit/ integration/ fixtures/   (real-data fixtures; synthetic cases are labelled SYNTHETIC)
data/        discovery/ (committed evidence)  raw/ processed/ warehouse/ (gitignored, local)
```

## Time semantics (read before using any feature)

`event_time` = tip-off; `published_at` is unknown for historical box scores and is **modelled** as `available_at = tip + 4h` (assumption,
`config.COMPLETION_BUFFER_H`); `fetched_at` is when we downloaded it and says nothing about knowability; `prediction_cutoff = tip − H`.
A history row is usable only if `available_at ≤ prediction_cutoff`. If tip time is unknown the engine falls back to a conservative
date-based rule and flags it. See `nba_props/features/cutoffs.py`.
