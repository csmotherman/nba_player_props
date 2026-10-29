# NBA Player Prop Data & Feature Engineering Blueprint

Technical source of truth for the NBA player-prop prediction system. **No prediction model has been built.** This document, the catalogs and the registry define what data exists, what can be calculated or estimated from it, and how to use it without leaking the future.

| File | Purpose |
|---|---|
| `NBA_DATA_BLUEPRINT.md` | This document: architecture, availability, methodology, modelling considerations, QC |
| `NBA_FEATURE_CATALOG.csv` | One row per feature: all metadata, formulas, sources, priority, validation status |
| `NBA_API_ENDPOINT_INVENTORY.csv` | One row per endpoint test (+ untested library endpoints): parameters, response fields, coverage, results |
| `NBA_FEATURE_DEPENDENCIES.md` | Per-market dependency pipelines and auto-generated graphs |
| `NBA_DATA_GAPS.md` | Missing data, external sources, substitutes, limitations, open tests |
| `nba_feature_registry.json` | Machine-readable registry (same content as the catalog, plus vocabularies and pipelines) for the Python pipeline |
| `nba_feature_explorer.html` | Offline searchable explorer (filter by market, data source, feature type, priority) |
| `scripts/` | Discovery, QC, registry source and build scripts; `data/discovery/` holds the raw results |

**Status labels used throughout.** Every statement about data is one of: *verified* (observed in a live response during discovery, with the evidence in `data/discovery/`), *derived* (follows from verified data by a stated formula), or *hypothesis/unverified* (not tested). Rankings of usefulness are hypotheses; none has been validated against outcomes.

---

## 1. How this audit was done

The request referred to earlier "endpoint discovery results". The repository was empty (no commits, no files) and nothing was installed, so discovery was performed from scratch:

* Library: `nba_api` **1.12.0** (142 endpoint classes: 138 stats + 4 live). Python 3.14.
* Date of discovery: **2026-10-29** (2026-27 regular season in progress, 68 regular-season games played).
* **439 recorded test calls** across five rounds (`scripts/discover_endpoints.py`, `discover_retry.py`, `discover_extra.py`, `discover_extra2.py`; raw JSON in `data/discovery/results_*.jsonl`). Which endpoint classes were exercised, and with what outcome, is tabulated below; untested classes are listed as `NOT_TESTED` in the inventory (mostly draft, awards, franchise, video and widget endpoints with no obvious prop value, but not individually assessed).
* Rounds: (1) sweep of ~160 calls with a known player/team/game; (2) retry of failures; (3) history probes (seasons 1946-47 to 2025-26, games from nine eras); (4) as-of/date-filter, in-progress-season and unplayed-game probes; (5) library parameters (`pace_adjust`, `period`, opponent shot locations).
* `scripts/qc_checks.py` reproduces the formula and coverage claims below and writes `data/discovery/qc_results.json`.
* Latency observed: most league-wide calls 0.2-1 s (median); `TeamDash*` and schedule calls 10-12 s; the first call of a session took 22 s. No rate limiting was encountered with 3 parallel threads over ~440 calls. This says nothing about sustained bulk backfills against an unofficial API.

<!-- BEGIN:counts -->

**Registry: 229 features.**

| Classification | Features |
|---|---|
| CALCULATED | 104 |
| RAW | 55 |
| ENGINEERED | 54 |
| UNVERIFIED | 8 |
| EXTERNAL | 8 |

| Priority | Meaning | Features |
|---|---|---|
| P0 | Minimum viable set - build first | 91 |
| P1 | High value - build after the MVP baseline works | 62 |
| P2 | Experimental - include only if ablation shows lift | 39 |
| P3 | Deferred - needs missing data or unproven reliability | 37 |

| Temporal status | Features |
|---|---|
| lagged_observed | 153 |
| projected | 36 |
| label | 15 |
| pregame_known | 9 |
| unverified | 8 |
| external_pregame | 8 |

| Validation status | Meaning | Features |
|---|---|---|
| formula_verified | Formula reproduced against API-provided columns on real data (data/discovery/qc_results.json) | 16 |
| source_verified | Source columns observed in a live response; derivation logic is standard but not independently tested | 129 |
| source_verified_untested_logic | Source observed live; the derivation/estimation logic is a hypothesis | 25 |
| hypothesis | Definition is a modelling proposal; nothing about its value has been tested | 43 |
| unverified_source | Source availability, depth or timing is not established | 8 |
| external_unobtained | Requires a source we do not have | 8 |

**Endpoint inventory: 237 rows** (142 library classes; 101 exercised, 41 not). Harness errors from my own wrong keyword names are excluded (1).

| Test status | Rows |
|---|---|
| OK | 174 |
| NOT_TESTED | 41 |
| FAILED | 10 |
| DEPRECATED_NO_DATA | 7 |
| OK_EMPTY | 5 |

<!-- END:counts -->

---

## 2. Classification and temporal status

**Classification (provenance of the data):**

| Class | Meaning |
|---|---|
| RAW | Directly available from a verified nba_api endpoint column |
| CALCULATED | Deterministic function of available data; no fitted parameters or judgment. Rolling means, ratios, formulas |
| ENGINEERED | Estimated, modelled or shrunk from multiple inputs. Contains fitted parameters, tuned hyper-parameters or a forecast |
| EXTERNAL | Needs a source outside nba_api |
| UNVERIFIED | Availability, depth, timing or reliability not established |

**Temporal status** (position relative to tip-off of the *target* game; enforced by `scripts/registry/checks.py`):

| Status | Meaning |
|---|---|
| `label` | Outcome of the target game. Never an input for that game |
| `lagged_observed` | Observed in completed games before the target; needs a strict as-of cutoff |
| `pregame_known` | Known before tip-off with no modelling (schedule, venue, rest) |
| `projected` | Model output built pregame; a *forecast*, not an observation |
| `external_pregame` | From a non-nba_api source, pregame |
| `unverified` | Pregame timing/availability not established |

A deterministic calculation and a statistical forecast are never given the same label. Example: `POS_TEAM_POSS_OBSERVED` (CALCULATED, postgame) vs `ENV_EXP_GAME_POSS` (ENGINEERED, projected).

---

## 3. Architecture

```
L0 raw ingest        nba_api responses stored verbatim, immutable, keyed by (endpoint, params, fetch_ts)
 |                   IDs as strings: GAME_ID '0022500600' (leading zeros matter)
L1 conformed tables  player_game, team_game, schedule, roster/status, game_summary(inactives, officials), tracking_day, pbp_event
 |                   season-type filter via GAME_ID[0:3]; one canonical row per (player, game)
L2 as-of feature store   every feature computed "as of" a cutoff timestamp; point-in-time correct by construction
 |                   rolling/EWMA/shrunk rates, team ratings, DvP tables, availability, context
L3 projections       minutes -> game environment -> on-court possessions -> opportunities (FGA, 3PA, potential assists, rebound chances ...)
 |                   outputs are distributions, not single numbers
L4 stat distributions  count models per market + joint simulation (shared minutes/pace) for combos
 |
L5 evaluation        walk-forward backtest, calibration, proper scoring, ablation harness, leakage tests
```

**Rules that make the store trustworthy**

1. **As-of everything.** A training row for game *g* on date *d* uses only information with timestamp < tip-off(*g*) minus the intended prediction lead. For nba_api this means either computing from L1 game rows with `date < d`, or passing `date_to_nullable = d - 1 day` to season endpoints (verified honored). Un-bounded `LeagueDash*` calls return data through *today* and leak.
2. **Training/serving symmetry.** Serving will see pregame statuses (Questionable/Probable) while a naive training set sees the realised inactive list. Build the training set from timestamped pregame snapshots or accept and quantify the optimism (see Gaps).
3. **Walk-forward evaluation only**, split by date. Never random k-fold across games.
4. **Store fetch timestamps** for any source that is a snapshot (live odds, standings, rosters). nba_api cannot backfill them.
5. **Keep raw and derived separated** so definitions can change without refetching.

**Collection plan by cost (approximate calls per season, from measured structure)**

| Dataset | Method | Calls/season |
|---|---|---|
| Player game logs (all measure types that worked) | `PlayerGameLogs`, season_type filter | ~6 |
| Team game logs (Base, Advanced, Four Factors, Misc, Scoring, Opponent) | `TeamGameLogs` | ~6 |
| Schedule | `ScheduleLeagueV2` | 1 |
| Starter flag, DNP comments, inactives, officials | `BoxScoreTraditionalV3` + `BoxScoreSummaryV3` per game | ~2,460 |
| Per-game tracking (potential assists, rebound chances, touches, drives) | `LeagueDashPtStats` single-day windows, one call per game date per measure | ~165 per measure |
| Per-game hustle (2016-17+) | `LeagueHustleStatsPlayer` single-day windows or `BoxScoreHustleV2` per game | ~165 or ~1,230 |
| As-of season-level dashboards (shot locations, catch-and-shoot, defend, on/off) | `date_to` snapshots, weekly | ~30-60 each |
| Defense vs position tables | `LeagueDashPlayerStats` opponent x position | 90 per refresh |
| Play-by-play (rotation reconstruction; optional) | `PlayByPlayV3` per game | ~1,230 |

---

## 4. Data availability (verified)

Details per endpoint are in `NBA_API_ENDPOINT_INVENTORY.csv`. Coverage statements list only seasons actually tested.

### 4.1 The datasets we actually have

| Dataset | Source | Verified coverage | Pregame? |
|---|---|---|---|
| Player box score per game | `LeagueGameLog` (P) | Rows in every tested season 1946-47 to 2026-27. STL/BLK/TOV/OREB/3PA populated from 1983-84 in tests; +/- from 1996-97 | Lagged |
| Advanced/usage/scoring per game | `PlayerGameLogs` (Base, Advanced, Usage, Scoring, Misc) | 2025-26, 2026-27 tested only | Lagged |
| Team box + advanced per game | `TeamGameLogs` (Base, Advanced, Four Factors, Misc, Scoring, Opponent) | 2025-26, 2026-27 tested only | Lagged |
| V3 box scores (6 flavours) | `BoxScore*V3` | 1996-97, 2007-08, 2013-14, 2017-18, 2018-19, 2019-20, 2025-26 | Lagged |
| Player tracking per game | `BoxScorePlayerTrackV3` | Values present 2013-14+; zeros in sampled earlier games | Lagged |
| Tracking aggregates, date-windowable | `LeagueDashPtStats` (12 measure types) | Possessions/Rebounding/Passing: 0 rows 2012-13, rows 2013-14 onward | Lagged with `date_to` |
| Hustle | `LeagueHustleStatsPlayer`, `BoxScoreHustleV2` | Full from 2016-17; 147 players in 2015-16; none 2014-15 | Lagged |
| Matchups | `LeagueSeasonMatchups`, `BoxScoreMatchupsV3`, `BoxScoreDefensiveV2` | 2017-18 onward | Lagged |
| Defender-level shot defence | `LeagueDashPtDefend` | 2013-14 onward (earlier untested) | Lagged |
| Play type (Synergy) | `SynergyPlayTypes` | 2014-15 onward (earlier untested) | Prior season |
| Shot-level data | `ShotChartDetail` | 1996-97, 2003-04, 2012-13, 2025-26 sampled | Lagged |
| Lineups / on-off | `LeagueDashLineups`, `TeamDashLineups`, `TeamPlayerOnOff*` | Lineups 2007-08 onward; returned exactly 2000 rows every time (suspect cap) | Lagged with `date_to` |
| Play-by-play | `PlayByPlayV3` | Sampled games 1996-97 to 2025-26 | Lagged |
| Schedule | `ScheduleLeagueV2` | 2025-26 (1,400 rows), 2026-27 (1,274 rows) | **Yes** |
| Market spread / moneyline | `nba_api.live` `Odds` | **Snapshot only**, 33 games; markets `2way` and `spread` only | **Yes (now)** |
| Inactive players, officials, DNP reason | `BoxScoreSummaryV3`, `BoxScoreTraditionalV3.comment` | Completed 2025-26 game verified | Empty ~4.5 h before tip |

### 4.2 Important discoveries

1. **Per-game potential assists and rebound chances are recoverable.** `BoxScorePlayerTrackV3` has no potential-assist column, but `LeagueDashPtStats` with `date_from = date_to = d` returns that day's per-player values. Verified on 2026-01-15: 201 players, `AST` equal to the game log for 100%, `POTENTIAL_AST` total 858. Depth of this trick beyond 2025-26 is untested.
2. **Starter flag is derivable historically.** `BoxScoreTraditionalV3.position` is non-empty for exactly the five starters (20 of 20 sampled games). It is not available pregame from nba_api.
3. **Game logs contain almost no DNP rows** (10.83 player rows per team-game; 83 zero-minute rows league-wide in 2025-26). Availability must be inferred from schedule x appearances, or taken from `InactivePlayers`.
4. **Defense versus position is constructible** with `LeagueDashPlayerStats(opponent_team_id, player_position_abbreviation_nullable, date_to_nullable)` (all three filters honored; positions are the NBA's three coarse buckets).
5. **Q4 minutes** are available via `period=4` (580 players), a blowout-sensitivity input.
6. **Pregame schedule exists, pregame injuries do not.** No nba_api endpoint is an injury report; `PlayerNextNGames` returned 0 rows in all three tests.

### 4.3 Dead, deprecated or broken (verified)

* `BoxScore{Advanced,Usage,Scoring,Misc,FourFactors}V2`, `PlayByPlayV2`: library marks deprecated ("returns empty JSON"); every call failed with `KeyError: 'resultSet'`. `BoxScoreTraditionalV2` returns rows for old games, empty for 2025-26. Use V3.
* `GameRotation` (official rotation chart): `JSONDecodeError` in every season tested. `WinProbabilityPBP`, `DefenseHub`, `TeamDashPtShots`: `JSONDecodeError`. Cause not established (blocked/removed vs parameters).
* `PlayerGameLogs` measure types `Four Factors` and `Defense`, `TeamGameLogs` `Defense`, `LeagueDashPlayerStats` `Four Factors`: failed.
* Empty results: `PlayerNextNGames`, `PlayerDashPtShotDefend`, `PlayerFantasyProfileBarGraph`.
* `ScoreboardV2` is documented as unreliable for line scores Oct 22 - Dec 25 2025; use `ScoreboardV3`.

### 4.4 Gotchas that will cause silent bugs

| Gotcha | Evidence |
|---|---|
| `GAME_ID` loses leading zeros if read as int, breaking joins | Happened during discovery |
| `PlayerGameLogs` without `season_type` mixes prefixes 001/002/003/004/005/006 (26,651 regular + 4,149 other rows in 2025-26) | `qc_results.json` |
| `TeamGameLogs.MIN` is 48 (regulation), not 240 | `qc_results.json` |
| `LeagueDashPlayerStats` Advanced reports `MIN` per game even when `per_mode=Totals` | Observed |
| `pace_adjust="Y"` had no effect (FGA identical) | Observed. Normalise pace yourself. `per_mode=Per100Possessions` works |
| API `TM_TOV_PCT` is `100*TOV/(FGA+0.44*FTA+AST+TOV)`, 0-100 scale, not a plain turnover % | r = 0.9994 |
| Usage and shares are fractions (0-1) in game logs | Observed |
| `POSS` is integer-rounded | 100% integer |
| Two-level column headers in `LeagueDash*ShotLocations` | Flatten as `Zone:Column` |
| Result-set names from nba_api are sometimes misaligned (`ScoreboardV2`, `CommonPlayerInfo`, `PlayByPlayV3`); rely on column signatures | Observed |
| `LeagueDashLineups` row count is exactly 2000 in every call | Probable cap; check with `TeamDashLineups` |
| `TIME_OF_POSS` unit is undocumented | Check before use |
| `opponent_team_id` semantics (lines of players facing that team) inferred from GP caps | Needs a direct reconciliation |

---

## 5. Feature engineering methodology

### 5.1 Principles

1. **Decompose every counting stat into opportunity x conversion**, and model each separately: `stat = minutes x possessions/minute x opportunities/possession x conversion`. Opportunities (minutes, attempts, potential assists, rebound chances) are more persistent and less opponent-dependent than results (FG%, 3P%, assist conversion).
2. **Shrink.** Every rate gets an empirical-Bayes or hierarchical estimate (`(n*obs + k*prior)/(n+k)`), with `k` fitted from data (beta-binomial MLE or cross-validation). Priors: prior season, then archetype, then league mean.
3. **Predict distributions.** Counts are overdispersed; points and combos are compounds. Use negative-binomial/binomial thinning and joint simulation with shared minutes and pace. Do not multiply expectations.
4. **Make minutes the first model.** Every market scales with minutes; errors in minutes dominate.
5. **Pace-normalise through possessions**, not through ad-hoc multipliers; use on-court possessions for player quantities.
6. **Separate observation from projection** in the feature store; never train on projected values computed with future data.
7. **No invented constants.** Where a coefficient is needed (shrinkage `k`, redistribution `lambda`/`gamma`, home-court term, EWMA half-life, blowout threshold) the registry says it is *estimated or tuned*, not known.

### 5.2 Verified building blocks (QC results)

| Quantity | Formula | Check against API (2025-26, regular season) |
|---|---|---|
| Usage | `((FGA + 0.44 FTA + TOV) * TeamMIN) / (MIN * (TmFGA + 0.44 TmFTA + TmTOV))`, TeamMIN = `TeamGameLogs.MIN` | MAE 0.0089, r = 0.9906 (n = 22,630) |
| True shooting | `PTS / (2 (FGA + 0.44 FTA))` | MAE 0.0002, r = 0.999999 |
| Assist % | `AST / ((MIN/TeamMIN) TmFGM - FGM)` | MAE 0.019, r = 0.966 |
| Rebound % | `REB TeamMIN / (MIN (TmREB + OppREB))` | MAE 0.014, r = 0.982 |
| OREB% / DREB% | analogues with opponent DREB / OREB | r = 0.979 / 0.965 |
| API turnover ratio | `100 TOV / (FGA + 0.44 FTA + AST + TOV)` | MAE 0.13, r = 0.9994 (plain TOV% variant: r = 0.956) |
| Team possessions (two-sided Oliver) | `0.5 [ (FGA + 0.4 FTA - 1.07 (OREB/(OREB+oppDREB))(FGA-FGM) + TOV) + (opp analogue) ]` | MAE 1.38, r = 0.965 |
| Team possessions (simple) | `FGA + 0.44 FTA - OREB + TOV` | MAE 2.27, r = 0.920 |
| Team pace | `48 POSS / TeamMIN` | MAE 0.40 (API POSS is integer) |
| Player on-court possessions | `POSS ~= on-court PACE x MIN / 48` | MAE 0.55, r = 0.999 |
| Rebound supply | total REB ~ `0.873 x FG misses + 0.075 x FTA + 1.70` | r = 0.90; mean REB 87.5 vs mean misses 94.3. **A proxy, not an identity** |

Own box-score formulas approximate but do not equal API values (the API uses tracking/PBP possessions). Do not mix API and own values within one model.

### 5.3 The "hidden" features requested

All are **ENGINEERED/projected** unless noted; none has been validated.

**Expected on-court possessions** `EXP_ONCOURT_POSS = k_i x PACE_exp x MIN_i / 48`
Team possessions are a game quantity; on-court possessions are a player quantity (verified relation above). `k_i = sum(POSS)/sum((MIN/48) x teamPOSS)` captures lineups that run faster or slower than the team. Pace is per 48 minutes, so overtime cancels at player level. `MIN_i` is a distribution, so possessions are too.

**Expected shot attempts** `EXP_FGA = poss_i x r_i`, `log r_i = log(FGA per 100 on-court possessions)/100 + beta . [opp_FGA_allowed, teammate_out, starter_prob, rest]` with betas learned. Equivalent per-minute form exists; the per-possession form is pace-neutral. These two are strongly collinear: keep one parameterisation, test the other in ablation.

**Expected rebound opportunities** `EXP_REB_CHANCES = ENV_EXP_MISSED_SHOTS x (E[MIN]/48) x share_i`, `share_i = rebound chances / (minutes-proportional available misses)`, then `EXP_REB = Binomial(chances, conversion)`. Because on-court misses are unknown without a rotation reconstruction (`GameRotation` is dead), the minutes-proportional approximation is an **unsupported assumption** to test. Expected misses come from both teams' miss-per-possession rates and the fitted rebound relation above.

**MVP baselines for rebounds and assists (no tracking data).** The opportunity pipelines need tracking aggregates, so the first version uses the verified percentage identities rearranged: `E[REB] = REB%_hat x (E[MIN]/48) x TotalREB_exp` and `E[AST] = AST%_hat x ((E[MIN]/48) x TmFGM_exp - FGM_exp)` (`EXP_REB_BASELINE`, `EXP_AST_BASELINE`). These are the benchmarks the opportunity x conversion pipelines must beat in ablation. Steals, blocks and turnovers use a count model over expected on-court possessions with optional opponent terms.

**Expected assist opportunities** `EXP_POT_AST = poss_i x potential assists per possession`, then `EXP_AST = Binomial(POT, c)` with `c` = shrunk conversion, optionally pass-destination-weighted by who is available (`PlayerDashPtPass` gives pass counts, assists, FGM/FGA per receiver). The cheaper team-level proxy (`AST_TEAM_ASSISTED_RATE`) should be tried first.

**Expected three-point attempts** `EXP_3PA = EXP_FGA x q_i`, `logit q_i = logit(3PA/FGA shrunk) + gamma . [opp_3PA_allowed, starter_prob, teammate_out]`; makes: `3PM | N ~ Binomial(N, p)`, `N ~ NegBin`, `p` = shrunk 3P% with at most a small opponent/shot-type adjustment. Expect opponent 3P% allowed to add very little (mostly shot luck); the ablation must decide.

**Usage redistribution** Two complementary tools, both with shrinkage: an empirical with/without effect per teammate pair (`USGR_WITH_WITHOUT`, confounded and low-n) and a pooled structural model `dFGA_i = lambda x V x w_i`, `w_i ∝ base_i^gamma` over eligible teammates, where `V` is the volume of absent players and `lambda in (0,1)` is the share re-allocated (the rest vanishes into replacement minutes and pace). `lambda` and `gamma` are estimated by regression on historical absences, not assumed. A minutes-vacancy model runs first because minutes are the first-order channel.

**Pace-adjusted defense vs position** Production allowed to position bucket *b* per opposing on-court possession, relative to the league rate for the same bucket, shrunk by possessions (`DVP_RATE_PACE_ADJ`). Compare against the team-level factor (`ADJ_OPP_ALLOWED_RATE`); the expectation, recorded as a hypothesis, is that most of DvP's signal is already in team defence and minutes. The three NBA position buckets are coarse; an archetype-cluster version (`DVP_ARCHETYPE_ALLOWED`) is the alternative.

**Role-change detection** CUSUM on minutes, starter transitions (from `position`), usage/touches z-shift, trade flags and teammate churn feed a composite `ROLE_CHANGE_FLAG` that down-weights stale history. Thresholds are tuned against known role changes.

**Opponent-adjusted recent form** `ADJ_PLAYER_ADJ_RATE` fits player and opponent effects jointly (ridge on `log(rate)`), and `ADJ_OPPORTUNITY_VS_RESULT_GAP` attributes a recent change to opportunities vs conversion. Opportunity changes are treated as persistent; conversion changes as mostly noise until shown otherwise.

**Game environment** Expected possessions, team points/total, expected missed shots and blowout probability (`ENV_*`, `BLO_*`). The spread proxy from team ratings is a fallback; market spreads (live snapshot, no history) are better.

**Additional defensible features identified**

* `AST_CONVERSION` vs `AST_TEAMMATE_CONVERSION_PROB`: opportunity/result split for assists (data: single-day windows).
* `REB_OPP_SHARE_PER_MISS`: rebound chances per available miss.
* `USG_ASSISTED_SHARE` (`PCT_AST_FGM`): dependence on teammate creation, which interacts with absences.
* `MIN_Q4_SHARE`, `BLO_HIST_BLOWOUT_MIN_LOSS`: player-specific blowout sensitivity.
* `VAR_STAT_CORR`, `VAR_NB_DISPERSION`, `VAR_ZERO_INFLATION`: distribution shape, essential for over/under probabilities and combo markets.
* `POS_ONCOURT_FACTOR`, `MIN_RETURN_RAMP`, `AVL_LOAD_MANAGEMENT_RISK`, `HOP_LAST5_MEETINGS_ENV`.
* `SHT_XFG` (shot quality), `ARC_PLAYTYPE_PROFILE`/`ARC_MATCHUP_PLAYTYPE_FIT`, `TRK_GRAVITY`: plausible but expensive or season-aggregate only; low priority.

---

## 6. Feature usefulness: hypothesis rankings

Scores below are **domain-informed hypotheses, not findings**. Score = `2 x predictive value + reliability + stability - collection cost - overfit risk`, each on a 1-3 scale (H/M/L mapped 3/2/1; cost and overfit risk count against). Leakage risk is a hard constraint, not a scoring term. Relevance per market is in the catalog (`rel_*`).

<!-- BEGIN:rankings -->

**PTS**  (top 10 of 95 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 2 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `POS_TEAM_DEF_RTG_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `POS_TEAM_OFF_RTG_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 5 | `POS_TEAM_PACE_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 6 | `USG_FGA_PER_100POSS` | CALCULATED | P0 | H | 10 | lagged_observed |
| 7 | `USG_FGA_PER_MIN` | CALCULATED | P0 | H | 10 | lagged_observed |
| 8 | `USG_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 9 | `MIN_START_FLAG_HIST` | CALCULATED | P0 | H | 9 | lagged_observed |
| 10 | `MIN_START_RATE` | CALCULATED | P0 | H | 9 | lagged_observed |

**REB**  (top 10 of 78 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 2 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `POS_TEAM_PACE_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `REB_AVAILABLE_MISSES_TEAM` | CALCULATED | P0 | H | 10 | lagged_observed |
| 5 | `REB_PCT_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 6 | `MIN_START_FLAG_HIST` | CALCULATED | P0 | H | 9 | lagged_observed |
| 7 | `MIN_START_RATE` | CALCULATED | P0 | H | 9 | lagged_observed |
| 8 | `REB_CHANCES_PER_MIN` | CALCULATED | P1 | H | 9 | lagged_observed |
| 9 | `ENV_EXP_GAME_POSS` | ENGINEERED | P0 | H | 8 | projected |
| 10 | `ENV_EXP_MISSED_SHOTS` | ENGINEERED | P0 | H | 8 | projected |

**AST**  (top 10 of 83 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `AST_PCT_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 2 | `AST_PER_100POSS` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 5 | `POS_TEAM_PACE_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 6 | `AST_POT_PER_100POSS` | CALCULATED | P1 | H | 9 | lagged_observed |
| 7 | `AST_POT_PER_MIN` | CALCULATED | P1 | H | 9 | lagged_observed |
| 8 | `MIN_START_FLAG_HIST` | CALCULATED | P0 | H | 9 | lagged_observed |
| 9 | `MIN_START_RATE` | CALCULATED | P0 | H | 9 | lagged_observed |
| 10 | `AST_CONVERSION_SHRUNK` | ENGINEERED | P1 | H | 8 | lagged_observed |

**3PM**  (top 10 of 80 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 2 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `POS_TEAM_PACE_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `TPT_3PA_PER_MIN` | CALCULATED | P0 | H | 10 | lagged_observed |
| 5 | `TPT_3PA_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 6 | `MIN_START_FLAG_HIST` | CALCULATED | P0 | H | 9 | lagged_observed |
| 7 | `MIN_START_RATE` | CALCULATED | P0 | H | 9 | lagged_observed |
| 8 | `TPT_3P_PCT_SHRUNK` | ENGINEERED | P0 | H | 9 | lagged_observed |
| 9 | `BOX_FG3A` | RAW | P0 | H | 8 | lagged_observed |
| 10 | `BOX_FG3M` | RAW | P0 | H | 8 | lagged_observed |

**STL**  (top 10 of 37 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `BLO_SPREAD_LIVE` | RAW | P1 | H | 10 | pregame_known |
| 2 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `BLO_SPREAD_HISTORICAL` ‡ | EXTERNAL | P1 | H | 9 | external_pregame |
| 5 | `ENV_EXP_GAME_POSS` | ENGINEERED | P0 | H | 8 | projected |
| 6 | `EXP_ONCOURT_POSS` | ENGINEERED | P0 | H | 8 | projected |
| 7 | `EXT_PROP_LINES` ‡ | EXTERNAL | P0 | H | 8 | external_pregame |
| 8 | `FRM_EWMA_RATE` | CALCULATED | P0 | H | 8 | lagged_observed |
| 9 | `FRM_PRIOR_SEASON_RATE` | CALCULATED | P0 | H | 8 | lagged_observed |
| 10 | `FRM_SHRUNK_RATE` | ENGINEERED | P0 | H | 8 | lagged_observed |

**BLK**  (top 10 of 41 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `BLO_SPREAD_LIVE` | RAW | P1 | H | 10 | pregame_known |
| 2 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `BLO_SPREAD_HISTORICAL` ‡ | EXTERNAL | P1 | H | 9 | external_pregame |
| 5 | `ENV_EXP_GAME_POSS` | ENGINEERED | P0 | H | 8 | projected |
| 6 | `EXP_ONCOURT_POSS` | ENGINEERED | P0 | H | 8 | projected |
| 7 | `EXT_PROP_LINES` ‡ | EXTERNAL | P0 | H | 8 | external_pregame |
| 8 | `FRM_EWMA_RATE` | CALCULATED | P0 | H | 8 | lagged_observed |
| 9 | `FRM_PRIOR_SEASON_RATE` | CALCULATED | P0 | H | 8 | lagged_observed |
| 10 | `FRM_SHRUNK_RATE` | ENGINEERED | P0 | H | 8 | lagged_observed |

**TOV**  (top 10 of 52 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `BLO_SPREAD_LIVE` | RAW | P1 | H | 10 | pregame_known |
| 2 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `POS_TEAM_PACE_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 5 | `TOV_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 6 | `USG_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 7 | `BLO_SPREAD_HISTORICAL` ‡ | EXTERNAL | P1 | H | 9 | external_pregame |
| 8 | `MIN_START_FLAG_HIST` | CALCULATED | P0 | H | 9 | lagged_observed |
| 9 | `MIN_START_RATE` | CALCULATED | P0 | H | 9 | lagged_observed |
| 10 | `ENV_EXP_GAME_POSS` | ENGINEERED | P0 | H | 8 | projected |

**COMBO**  (top 10 of 91 candidates with High/Medium relevance; ‡ = external or unverified source)

| # | Feature | Class | Pri | Relevance | Score | Temporal |
|---|---|---|---|---|---|---|
| 1 | `FRM_ROLL_RATE` | CALCULATED | P0 | H | 10 | lagged_observed |
| 2 | `MIN_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 3 | `POS_TEAM_PACE_ROLL` | CALCULATED | P0 | H | 10 | lagged_observed |
| 4 | `MIN_START_FLAG_HIST` | CALCULATED | P0 | H | 9 | lagged_observed |
| 5 | `MIN_START_RATE` | CALCULATED | P0 | H | 9 | lagged_observed |
| 6 | `ENV_EXP_GAME_POSS` | ENGINEERED | P0 | H | 8 | projected |
| 7 | `EXP_ONCOURT_POSS` | ENGINEERED | P0 | H | 8 | projected |
| 8 | `EXT_PROP_LINES` ‡ | EXTERNAL | P0 | H | 8 | external_pregame |
| 9 | `FRM_EWMA_RATE` | CALCULATED | P0 | H | 8 | lagged_observed |
| 10 | `FRM_PRIOR_SEASON_RATE` | CALCULATED | P0 | H | 8 | lagged_observed |


<!-- END:rankings -->

### 6.1 Highly correlated or duplicated candidates

Declared correlation clusters (features that measure largely the same thing, so keep one or build them hierarchically):

<!-- BEGIN:clusters -->

| Cluster | Size | Members |
|---|---|---|
| box_volume | 11 | `BOX_FGM`, `BOX_FGA`, `BOX_FG3M`, `BOX_FG3A`, `BOX_FTM`, `BOX_FTA`, `BOX_OREB`, `BOX_DREB`, `BOX_PF`, `BOX_PFD`, `BOX_BLKA` |
| shot_mix | 9 | `BOX_PCT_FGA_3PT`, `BOX_PCT_AST_FGM`, `BOX_PCT_PTS_PAINT`, `BOX_PCT_PTS_FB`, `BOX_PCT_UAST_3PM`, `USG_ASSISTED_SHARE`, `SHT_ZONE_FREQ`, `SHT_CATCH_SHOOT_SHARE`, `SHT_OPEN_SHOT_RATE` |
| availability | 9 | `AVL_PLAYED_FLAG_HIST`, `AVL_INACTIVE_LIST_HIST`, `AVL_DNP_REASON_HIST`, `AVL_GAMES_MISSED_STREAK`, `AVL_TEAMMATE_OUT_USAGE`, `AVL_OPP_KEY_PLAYER_OUT`, `AVL_LOAD_MANAGEMENT_RISK`, `EXT_INJURY_REPORT`, `EXT_NEWS_TRANSACTIONS` |
| usage_shares | 8 | `BOX_PCT_FGA`, `BOX_PCT_FG3A`, `BOX_PCT_AST`, `BOX_PCT_REB`, `BOX_PCT_TOV`, `BOX_PCT_STL`, `BOX_PCT_BLK`, `BOX_PCT_PTS` |
| blowout | 8 | `MIN_Q4_SHARE`, `BLO_SPREAD_LIVE`, `BLO_SPREAD_HISTORICAL`, `BLO_RATING_SPREAD_PROXY`, `BLO_PROB_BLOWOUT`, `BLO_HIST_BLOWOUT_MIN_LOSS`, `BLO_TEAM_CLOSE_RATE`, `BLO_GARBAGE_TIME_FLAG` |
| form | 8 | `ADJ_PLAYER_ADJ_RATE`, `ADJ_SCHEDULE_STRENGTH_L10`, `ADJ_OPPORTUNITY_VS_RESULT_GAP`, `FRM_ROLL_RATE`, `FRM_EWMA_RATE`, `FRM_SHRUNK_RATE`, `FRM_PRIOR_SEASON_RATE`, `FRM_TREND_SLOPE` |
| role | 7 | `ROLE_CUSUM_MINUTES`, `ROLE_USAGE_SHIFT`, `ROLE_START_STATUS_CHANGE`, `ROLE_TEAM_CHANGE`, `ROLE_TEAMMATE_CHURN`, `ROLE_CHANGE_FLAG`, `ROLE_COACH_CHANGE` |
| variance | 7 | `VAR_NB_DISPERSION`, `VAR_ROLL_STD`, `VAR_QUANTILES_EMP`, `VAR_ZERO_INFLATION`, `VAR_STAT_CORR`, `VAR_MIN_VOLATILITY`, `VAR_STREAK_AUTOCORR` |
| usage | 6 | `USG_ROLL`, `USG_USG_FORMULA`, `USG_FGA_PER_MIN`, `USG_FGA_PER_100POSS`, `USG_FTA_RATE`, `USG_COMPETITION_ONCOURT` |
| pace | 6 | `POS_TEAM_POSS_OBSERVED`, `POS_TEAM_PACE_ROLL`, `POS_MATCHUP_PACE_EXP`, `POS_ONCOURT_FACTOR`, `POS_PLAYTYPE_TRANSITION_FREQ`, `ENV_EXP_GAME_POSS` |
| archetype | 6 | `ARC_POSITION`, `ARC_SIZE`, `ARC_CLUSTER_ID`, `ARC_PLAYTYPE_PROFILE`, `ARC_MATCHUP_PLAYTYPE_FIT`, `ARC_SIZE_MISMATCH` |
| context | 5 | `BOX_GAME_TYPE`, `CTX_HOME`, `CTX_HOME_AWAY_SPLIT`, `CTX_STANDINGS_MOTIVATION`, `CTX_GAME_META` |
| rest | 5 | `MIN_BACK_TO_BACK_DELTA`, `CTX_DAYS_REST`, `CTX_B2B`, `CTX_REST_DIFF`, `CTX_TRAVEL_GEO` |
| efficiency | 5 | `SHT_TS_ROLL`, `SHT_FG_PCT_SHRUNK`, `SHT_FT_PCT_SHRUNK`, `SHT_XFG`, `SHT_PTS_PER_SHOT` |
| reb_opportunity | 5 | `REB_CHANCES_PER_MIN`, `REB_OPP_SHARE_PER_MISS`, `REB_BOXOUTS_PER_MIN`, `REB_DISTANCE_PROFILE`, `REB_FRONTCOURT_COMPETITION` |
| starter | 4 | `MIN_START_FLAG_HIST`, `MIN_START_RATE`, `MIN_START_PROB_TODAY`, `EXT_CONFIRMED_STARTERS` |
| tracking_touch | 4 | `USG_TOUCHES_PER_MIN`, `USG_TIME_OF_POSS`, `SHT_DRIVE_RATE`, `AST_PASSES_PER_MIN` |
| assist_opportunity | 4 | `AST_POT_PER_MIN`, `AST_POT_PER_100POSS`, `AST_SECONDARY_FT_AST`, `AST_BALLHANDLER_COMPETITION` |
| dvp | 4 | `DVP_ALLOWED_RAW`, `DVP_RATE_PACE_ADJ`, `DVP_ARCHETYPE_ALLOWED`, `DVP_PRIMARY_DEFENDER_HIST` |
| on_off | 4 | `LIN_ONOFF_RATING`, `LIN_ONOFF_TEAM_RATES`, `LIN_LINEUP_NET_PACE`, `LIN_EXPECTED_ROTATION_QUALITY` |
| aux_targets | 3 | `LBL_FGA`, `LBL_FG3A`, `LBL_MIN` |
| REB_RATE | 3 | `BOX_REB_PCT`, `BOX_OREB_PCT`, `BOX_DREB_PCT` |
| three_volume | 3 | `TPT_3PA_PER_MIN`, `TPT_3PA_RATE`, `TPT_CS_3PA_SHARE` |
| three_efficiency | 3 | `TPT_3P_PCT_SHRUNK`, `TPT_CORNER_SHARE`, `TPT_WIDE_OPEN_RATE` |
| assist_conversion | 3 | `AST_CONVERSION`, `AST_CONVERSION_SHRUNK`, `AST_TEAMMATE_CONVERSION_PROB` |
| reb_supply | 3 | `REB_AVAILABLE_MISSES_TEAM`, `REB_OPP_OREB_ALLOWED`, `REB_OPP_3PA_LONG_REBOUND_ENV` |
| turnover | 3 | `TOV_RATE`, `TOV_PER_USAGE`, `TOV_DRIVE_TOV_RATE` |
| team_rating | 3 | `POS_TEAM_OFF_RTG_ROLL`, `POS_TEAM_DEF_RTG_ROLL`, `POS_TEAM_FOUR_FACTORS` |
| opp_defense | 3 | `POS_OPP_SHOT_PROFILE_ALLOWED`, `ADJ_OPP_ALLOWED_RATE`, `DVP_OPP_RIM_PROTECTION` |
| tracking_other | 3 | `TRK_SPEED_DISTANCE`, `TRK_CONTESTED_FG_SHARE`, `TRK_GRAVITY` |
| scoring_pipeline | 3 | `EXP_FGA`, `EXP_FTA`, `EXP_PTS_DIST` |
| three_pipeline | 3 | `EXP_3PA`, `EXP_3P_PCT`, `EXP_3PM_DIST` |
| assist_pipeline | 3 | `EXP_POT_AST`, `EXP_AST_DIST`, `EXP_AST_BASELINE` |
| reb_pipeline | 3 | `EXP_REB_CHANCES`, `EXP_REB_DIST`, `EXP_REB_BASELINE` |
| usage_redistribution | 3 | `USGR_WITH_WITHOUT`, `USGR_POOLED_ELASTICITY`, `USGR_MINUTES_VACANCY` |
| hop | 3 | `HOP_PLAYER_VS_OPP_RATE`, `HOP_LAST5_MEETINGS_ENV`, `HOP_REF_CREW_FOUL_RATE` |
| EFF | 2 | `BOX_TS_PCT`, `BOX_EFG_PCT` |
| PACE | 2 | `BOX_PACE`, `BOX_POSS` |
| rating | 2 | `BOX_OFF_RATING`, `BOX_DEF_RATING` |
| minutes_history | 2 | `MIN_ROLL`, `MIN_EWMA` |
| opp_three | 2 | `TPT_OPP_3PA_ALLOWED`, `TPT_OPP_3P_PCT_ALLOWED` |
| team_style | 2 | `AST_TEAM_ASSISTED_RATE`, `POS_TEAM_STYLE_PROFILE` |
| assist_rate | 2 | `AST_PCT_ROLL`, `AST_PER_100POSS` |
| reb_conversion | 2 | `REB_CONVERSION`, `REB_CONVERSION_SHRUNK` |
| steal | 2 | `STL_RATE`, `STL_DEFLECTIONS_PER_MIN` |
| opp_turnover | 2 | `STL_OPP_TOV_RATE`, `TOV_OPP_PRESSURE` |
| block | 2 | `BLK_RATE`, `BLK_RIM_DEFENDED_PER_MIN` |
| opp_block | 2 | `BLK_OPP_RIM_ATTEMPT_RATE`, `BLK_OPP_2PA_ALLOWED` |
| game_env | 2 | `ENV_EXP_TEAM_POINTS`, `ENV_EXP_MISSED_SHOTS` |

<!-- END:clusters -->

Known exact or near-duplicates: `SHT_PTS_PER_SHOT` = 2 x `SHT_TS_ROLL`; `USG_FGA_PER_MIN` x pace ~ `USG_FGA_PER_100POSS`; `TPT_3PA_PER_MIN` = `TPT_3PA_RATE` x `USG_FGA_PER_MIN`; `AST_PCT_ROLL` ~ `AST_PER_100POSS`; `BOX_USG_PCT` vs `USG_USG_FORMULA`; `FRM_ROLL_RATE`, `FRM_EWMA_RATE` and `FRM_SHRUNK_RATE` are nested.

### 6.2 What must be evaluated through ablation

Rule: a feature earns a place only if it improves walk-forward out-of-sample **CRPS / log score and calibration** (not just MAE) for at least one market, with a paired bootstrap over game-days. Ablate in blocks against the baseline.

**Highest-priority ablation questions**

1. Per-minute vs per-possession parameterisation of attempts (`USG_FGA_PER_MIN` vs `USG_FGA_PER_100POSS`).
2. Does the opportunity layer (potential assists, rebound chances) beat the rate layer (`AST_PCT`, `REB_PCT`) at equal minutes forecasts?
3. Does `DVP_RATE_PACE_ADJ` add anything over `ADJ_OPP_ALLOWED_RATE` + team ratings?
4. Does opponent 3P% allowed (`TPT_OPP_3P_PCT_ALLOWED`) help at all? (Expected: no.)
5. Pooled redistribution (`USGR_POOLED_ELASTICITY`) vs raw teammate-out flags.
6. `HOP_PLAYER_VS_OPP_RATE` (expected: noise).
7. Archetype clusters as prior / DvP key vs listed position.
8. `MIN_START_PROB_TODAY`, `MIN_FOUL_TROUBLE_RATE`, back-to-back delta: incremental minutes lift.
9. Rolling window choice and EWMA half-lives per stat; EB shrinkage vs raw windows.
10. Tracking-derived touches/drives/time-of-possession over USG + AST%.
11. Rebound supply: minutes-proportional misses vs reconstructed on-court misses (if rotation recon ever works).
12. Market spread vs rating-proxy for blowout probability.

All ablation groups (the `ablation_group` field) and their members:

<!-- BEGIN:ablation -->

| Group | Size | Typical priority | Members |
|---|---|---|---|
| api_advanced | 13 | P0 | `BOX_USG_PCT`, `BOX_TS_PCT`, `BOX_EFG_PCT`, `BOX_AST_PCT`, `BOX_REB_PCT`, `BOX_OREB_PCT`, `BOX_DREB_PCT`, `BOX_TM_TOV_PCT`, `BOX_PACE`, `BOX_POSS`, `BOX_PIE`, `BOX_OFF_RATING`, `BOX_DEF_RATING` |
| box_core | 13 | P0 | `BOX_FGM`, `BOX_FGA`, `BOX_FG3M`, `BOX_FG3A`, `BOX_FTM`, `BOX_FTA`, `BOX_OREB`, `BOX_DREB`, `BOX_PF`, `BOX_PFD`, `BOX_BLKA`, `BOX_PLUS_MINUS`, `BOX_WL` |
| opp_defense | 11 | P1 | `TPT_OPP_3PA_ALLOWED`, `TPT_OPP_3P_PCT_ALLOWED`, `AST_OPP_ASSISTS_ALLOWED`, `STL_OPP_TOV_RATE`, `BLK_OPP_RIM_ATTEMPT_RATE`, `BLK_OPP_2PA_ALLOWED`, `TOV_OPP_PRESSURE`, `POS_OPP_SHOT_PROFILE_ALLOWED`, `ADJ_OPP_ALLOWED_RATE`, `DVP_OPP_RIM_PROTECTION`, `AVL_OPP_KEY_PLAYER_OUT` |
| context_core | 9 | P3 | `BOX_GAME_TYPE`, `CTX_HOME`, `CTX_DAYS_REST`, `CTX_B2B`, `CTX_REST_DIFF`, `CTX_HOME_AWAY_SPLIT`, `CTX_TRAVEL_GEO`, `CTX_STANDINGS_MOTIVATION`, `CTX_GAME_META` |
| availability | 8 | P0 | `AVL_PLAYED_FLAG_HIST`, `AVL_INACTIVE_LIST_HIST`, `AVL_DNP_REASON_HIST`, `AVL_GAMES_MISSED_STREAK`, `AVL_TEAMMATE_OUT_USAGE`, `AVL_LOAD_MANAGEMENT_RISK`, `EXT_INJURY_REPORT`, `EXT_NEWS_TRANSACTIONS` |
| usage_shares | 8 | P1 | `BOX_PCT_FGA`, `BOX_PCT_FG3A`, `BOX_PCT_AST`, `BOX_PCT_REB`, `BOX_PCT_TOV`, `BOX_PCT_STL`, `BOX_PCT_BLK`, `BOX_PCT_PTS` |
| minutes_core | 7 | P0 | `MIN_ROLL`, `MIN_EWMA`, `MIN_START_FLAG_HIST`, `MIN_START_RATE`, `MIN_START_PROB_TODAY`, `MIN_EXP`, `EXT_CONFIRMED_STARTERS` |
| role_change | 7 | P1 | `ROLE_CUSUM_MINUTES`, `ROLE_USAGE_SHIFT`, `ROLE_START_STATUS_CHANGE`, `ROLE_TEAM_CHANGE`, `ROLE_TEAMMATE_CHURN`, `ROLE_CHANGE_FLAG`, `ROLE_COACH_CHANGE` |
| variance | 7 | P1 | `VAR_NB_DISPERSION`, `VAR_ROLL_STD`, `VAR_QUANTILES_EMP`, `VAR_ZERO_INFLATION`, `VAR_STAT_CORR`, `VAR_MIN_VOLATILITY`, `VAR_STREAK_AUTOCORR` |
| scoring_mix | 6 | P2 | `BOX_PCT_FGA_3PT`, `BOX_PCT_AST_FGM`, `BOX_PCT_PTS_PAINT`, `BOX_PCT_PTS_FB`, `BOX_PCT_UAST_3PM`, `USG_ASSISTED_SHARE` |
| usage_redistribution | 6 | P2 | `USG_COMPETITION_ONCOURT`, `AST_BALLHANDLER_COMPETITION`, `REB_FRONTCOURT_COMPETITION`, `USGR_WITH_WITHOUT`, `USGR_POOLED_ELASTICITY`, `LIN_EXPECTED_ROTATION_QUALITY` |
| blowout | 5 | P1 | `BLO_SPREAD_LIVE`, `BLO_SPREAD_HISTORICAL`, `BLO_RATING_SPREAD_PROXY`, `BLO_PROB_BLOWOUT`, `BLO_TEAM_CLOSE_RATE` |
| form_core | 5 | P0 | `FRM_ROLL_RATE`, `FRM_EWMA_RATE`, `FRM_SHRUNK_RATE`, `FRM_PRIOR_SEASON_RATE`, `FRM_TREND_SLOPE` |
| pace | 5 | P0 | `POS_TEAM_POSS_OBSERVED`, `POS_TEAM_PACE_ROLL`, `POS_MATCHUP_PACE_EXP`, `POS_ONCOURT_FACTOR`, `ENV_EXP_GAME_POSS` |
| three_efficiency | 5 | P0 | `TPT_3P_PCT_SHRUNK`, `TPT_CORNER_SHARE`, `TPT_WIDE_OPEN_RATE`, `EXP_3P_PCT`, `EXP_3PM_DIST` |
| tracking_touch | 5 | P2 | `USG_TOUCHES_PER_MIN`, `USG_TIME_OF_POSS`, `SHT_DRIVE_RATE`, `AST_PASSES_PER_MIN`, `TOV_DRIVE_TOV_RATE` |
| archetype | 4 | P0 | `ARC_POSITION`, `ARC_SIZE`, `ARC_CLUSTER_ID`, `ARC_SIZE_MISMATCH` |
| assist_conversion | 4 | P1 | `AST_CONVERSION`, `AST_CONVERSION_SHRUNK`, `AST_TEAMMATE_CONVERSION_PROB`, `EXP_AST_DIST` |
| assist_opportunity | 4 | P1 | `AST_POT_PER_MIN`, `AST_POT_PER_100POSS`, `AST_SECONDARY_FT_AST`, `EXP_POT_AST` |
| dvp | 4 | P1 | `DVP_ALLOWED_RAW`, `DVP_RATE_PACE_ADJ`, `DVP_ARCHETYPE_ALLOWED`, `DVP_PRIMARY_DEFENDER_HIST` |
| efficiency | 4 | P3 | `SHT_TS_ROLL`, `SHT_FG_PCT_SHRUNK`, `SHT_XFG`, `SHT_PTS_PER_SHOT` |
| reb_opportunity | 4 | P1 | `REB_CHANCES_PER_MIN`, `REB_OPP_SHARE_PER_MISS`, `EXP_REB_CHANCES`, `EXP_REB_BASELINE` |
| shot_mix | 4 | P3 | `SHT_ZONE_FREQ`, `SHT_CATCH_SHOOT_SHARE`, `SHT_OPEN_SHOT_RATE`, `TRK_CONTESTED_FG_SHARE` |
| team_style | 4 | P1 | `AST_TEAM_ASSISTED_RATE`, `REB_OPP_OREB_ALLOWED`, `REB_OPP_3PA_LONG_REBOUND_ENV`, `POS_TEAM_STYLE_PROFILE` |
| three_volume | 4 | P0 | `TPT_3PA_PER_MIN`, `TPT_3PA_RATE`, `TPT_CS_3PA_SHARE`, `EXP_3PA` |
| usage_core | 4 | P0 | `USG_ROLL`, `USG_USG_FORMULA`, `USG_FGA_PER_MIN`, `USG_FGA_PER_100POSS` |
| assist_rate | 3 | P0 | `AST_PCT_ROLL`, `AST_PER_100POSS`, `EXP_AST_BASELINE` |
| blk_core | 3 | P0 | `BLK_RATE`, `BLK_RIM_DEFENDED_PER_MIN`, `EXP_BLK_DIST` |
| form_adjusted | 3 | P1 | `ADJ_PLAYER_ADJ_RATE`, `ADJ_SCHEDULE_STRENGTH_L10`, `ADJ_OPPORTUNITY_VS_RESULT_GAP` |
| hop | 3 | P3 | `HOP_PLAYER_VS_OPP_RATE`, `HOP_LAST5_MEETINGS_ENV`, `HOP_REF_CREW_FOUL_RATE` |
| on_off | 3 | P3 | `LIN_ONOFF_RATING`, `LIN_ONOFF_TEAM_RATES`, `LIN_LINEUP_NET_PACE` |
| opportunity_core | 3 | P0 | `EXP_ONCOURT_POSS`, `EXP_FGA`, `EXP_FTA` |
| playtype | 3 | P3 | `POS_PLAYTYPE_TRANSITION_FREQ`, `ARC_PLAYTYPE_PROFILE`, `ARC_MATCHUP_PLAYTYPE_FIT` |
| reb_conversion | 3 | P1 | `REB_CONVERSION`, `REB_CONVERSION_SHRUNK`, `EXP_REB_DIST` |
| team_rating | 3 | P0 | `POS_TEAM_OFF_RTG_ROLL`, `POS_TEAM_DEF_RTG_ROLL`, `POS_TEAM_FOUR_FACTORS` |
| tov_core | 3 | P0 | `TOV_RATE`, `TOV_PER_USAGE`, `EXP_TOV_DIST` |
| hustle | 2 | P3 | `REB_BOXOUTS_PER_MIN`, `STL_DEFLECTIONS_PER_MIN` |
| minutes_availability | 2 | P1 | `MIN_RETURN_RAMP`, `USGR_MINUTES_VACANCY` |
| minutes_blowout | 2 | P2 | `MIN_Q4_SHARE`, `BLO_HIST_BLOWOUT_MIN_LOSS` |
| reb_supply | 2 | P0 | `REB_AVAILABLE_MISSES_TEAM`, `ENV_EXP_MISSED_SHOTS` |
| rotation_recon | 2 | P3 | `MIN_ROTATION_RECON`, `BLO_GARBAGE_TIME_FLAG` |
| shooting_free_throws | 2 | P0 | `USG_FTA_RATE`, `SHT_FT_PCT_SHRUNK` |
| stl_core | 2 | P0 | `STL_RATE`, `EXP_STL_DIST` |
| tracking_other | 2 | P3 | `TRK_SPEED_DISTANCE`, `TRK_GRAVITY` |

<!-- END:ablation -->

---

## 7. Modelling considerations

* **Targets.** Model each market as a distribution: minutes (mixture with a DNP/limited-play mass) -> opportunities -> conversions -> counts. Points via attempts x efficiency by shot type; assists via potential assists x conversion; rebounds via chances x conversion; threes via attempts x make probability; steals/blocks/turnovers as zero-heavy counts over on-court possessions. Combo markets need joint simulation (`VAR_STAT_CORR`) because shared minutes/pace induce correlation.
* **Probabilities, not point estimates.** The decision variable is `P(stat > line)`; evaluate with CRPS/log score and reliability curves. MAE alone rewards the wrong thing.
* **Lines.** The prop line is an extremely strong signal. Using it as a feature changes the problem from "predict the stat" to "beat the market". Decide explicitly; keep a stat-only model for edge detection and compare. Historical prop lines are not available from nba_api (see Gaps).
* **Sample size.** Single-game stats are tiny samples; pooled/hierarchical estimation is the main defence against overfitting. Archetype-level pooling for rookies and returners.
* **Early season and role resets.** Use prior-season priors with decay; flag low-sample players; widen predictive intervals.
* **Regime change.** Rules/pace trends shift between seasons; fit with season-aware offsets or recent-season weighting.
* **Availability uncertainty.** Carry probabilities (Out/Doubtful/Questionable) through the minutes mixture rather than hard flags.
* **Train/serve skew.** See architecture rule 2.
* **Evaluation hygiene.** Walk-forward by date; freeze feature definitions before looking at test seasons; track the number of ablations run to control selective reporting; test with preseason and playoffs excluded unless modelled.
* **Infrastructure.** nba_api is an unofficial client of undocumented endpoints; endpoints were deprecated mid-season in the past (V2 box scores), calls time out, and some return empty bodies. Cache raw responses, retry with backoff, version the schema, monitor row counts per call.

---

## 8. Quality control

### 8.1 Executable checks (`scripts/registry/checks.py`, run on every build)

* Every source column of every feature is looked up in the columns actually observed in live responses of that endpoint (and measure-type variant). Result: **0 unmapped** across every feature in the registry.
* All dependencies resolve; **no cycles**; optional dependencies are marked.
* Temporal consistency: a `label` is never available pregame; any postgame quantity cannot be rated Low leakage; a `projected` or `pregame_known` feature cannot reach a `label` except through a `lagged_observed` node.
* Every `formula_verified` claim must be backed by a threshold on `qc_results.json` (e.g. usage r >= 0.98).
* UNVERIFIED features cannot be P0.
* The validator was **mutation-tested**: injecting a fake column, a missing dependency, a projected->label path, an unbacked "verified" claim, a cycle, a pregame label and a postgame-Low rating were all caught.
* Bugs the checks caught in this registry during construction: a reference to a non-existent redistribution feature, an inconsistent pregame flag, and several P0 features depending on lower-priority ones (resolved by promoting cheap verified inputs and marking the rest optional).

### 8.2 Leakage register (highest risks)

1. **Un-bounded season endpoints** (`LeagueDash*`, `PlayerDash*`, `TeamDash*`) include games after the target date. Always pass `date_to_nullable`.
2. **`PlayerGameLogs` mixes season types**, including future playoff games when sliced by season.
3. **Final-season ratings** used for opponents in earlier games (use ratings as of each game date).
4. **Roster/absence inference** that looks at games after the target date.
5. **Standings and rosters** from `LeagueStandingsV3` / `CommonTeamRoster` are current snapshots.
6. **Realised inactive lists** used as if known 24 h earlier; **closing lines** used for earlier decisions.
7. **Shrinkage/EB parameters or clusters fitted on the full dataset** (fit inside each training window).
8. **Postgame-only fields** (`USG_PCT` etc. of the target game) accidentally used as features instead of lagged versions.
9. **Season-aggregate `GravityLeaders`, `SynergyPlayTypes`** current-season values include the future; use prior season.
10. **Target encoding of player IDs** across the split.

The catalog's `leakage_risk` and `leakage_notes` carry the per-feature version.

### 8.3 Observed vs projected

Every feature has `temporal_status`. Observed: `label`, `lagged_observed`, `pregame_known`. Projected: `projected` (count in section 1). Mixing the two in one column (e.g. filling a missing observed value with a projection) is prohibited; keep separate columns with an indicator.

### 8.4 Unsupported assumptions (flagged, not resolved)

* Minutes-proportional allocation of missed shots to a player's minutes (no rotation data).
* Additive pace and rating combination for game environment (`POS_MATCHUP_PACE_EXP`, `ENV_EXP_TEAM_POINTS`).
* OPP_* semantics in `TeamGameLogs[Opponent]` (sign/ownership) must be confirmed on one game before use.
* `opponent_team_id` + position filter returns the lines of players facing that team (inferred).
* `TIME_OF_POSS` unit.
* `LeagueDashLineups` completeness.
* Single-day tracking windows beyond 2025-26.
* Heuristic roster-membership inference for absences.
* Redistribution elasticities, shrinkage strengths, EWMA half-lives, blowout threshold, change-point thresholds: all tuned, none known.
* "Historical availability" statements cover **tested seasons only**; intermediate and unsampled seasons are untested.

### 8.5 Still needs testing (see also `NBA_DATA_GAPS.md` section 6)

Depth of single-day tracking windows; V3 summary (inactives/officials) in earlier seasons; whether inactives and officials appear pregame (and when); `PlayerGameLogs`/`TeamGameLogs` history depth; `SynergyPlayTypes` date filters; `LeagueDashLineups` cap; sustained-throughput limits; why `DefenseHub`, `GameRotation`, `TeamDashPtShots`, `WinProbabilityPBP` fail; the 24 regular-season games missing from the 2026-27 schedule listing (1,206 of the 1,230 expected `002` ids were returned).

---

## 9. Final recommendation (summary)

1. **Most valuable datasets we have:** `LeagueGameLog`/`PlayerGameLogs`/`TeamGameLogs` (the backbone); `LeagueDashPtStats` with date windows (potential assists, rebound chances, touches); `BoxScoreTraditionalV3` (starters, DNP comments); `BoxScoreSummaryV3` (inactives, last-five meetings); `ScheduleLeagueV2` (rest, home); `LeagueDashPlayerStats` with opponent/position/date filters (DvP); live `Odds` (spread snapshot).
2. **Most valuable new features:** projected minutes; expected on-court possessions; potential assists per possession x conversion; rebound chances x conversion; shrunk attempt rates; teammate-absence minutes/usage redistribution; blowout-adjusted minutes.
3. **Promising but hard:** true on-court missed-shot counts (needs rotation reconstruction); pass-destination teammate conversion; pregame lineup/usage redistribution under uncertain availability; defender-assignment-aware matchup features; archetype clustering that earns its keep.
4. **Missing sources:** pregame injury/status feed, confirmed starters, historical and live prop lines and totals, pregame officials, minute-restriction news, travel/arena geodata.
5. **Minimum viable set:** the P0 features listed below (single authority: `scripts/registry/priorities.py`): minutes layer, pace/possession layer, shrunk rates, opponent factors, availability history, variance, plus labels and raw ingest. The blocked externals (`EXT_INJURY_REPORT`, `AVL_TEAMMATE_OUT_USAGE`, `EXT_PROP_LINES`) are needed for serving and for betting backtests.

<!-- BEGIN:mvp -->

P0 = 91 features: 15 labels, 17 raw-ingest columns, **56 modelled features using nba_api data only**, and 3 blocked by external data.

| Domain | P0 features (‡ = needs external data) |
|---|---|
| Blowout risk and game competitiveness | `BLO_RATING_SPREAD_PROXY`, `BLO_PROB_BLOWOUT`, `BLO_HIST_BLOWOUT_MIN_LOSS` |
| Expected opportunities (projected) | `EXP_ONCOURT_POSS`, `EXP_FGA`, `EXP_FTA`, `EXP_3PA`, `EXP_3P_PCT`, `EXP_3PM_DIST`, `EXP_PTS_DIST`, `EXP_STL_DIST`, `EXP_BLK_DIST`, `EXP_TOV_DIST`, `EXP_REB_BASELINE`, `EXP_AST_BASELINE` |
| External data | `EXT_INJURY_REPORT` ‡, `EXT_PROP_LINES` ‡ |
| Game environment | `ENV_EXP_GAME_POSS`, `ENV_EXP_MISSED_SHOTS` |
| Game-level statistical variance | `VAR_NB_DISPERSION` |
| Home/away and rest | `CTX_HOME`, `CTX_DAYS_REST` |
| Minutes and rotation | `MIN_ROLL`, `MIN_EWMA`, `MIN_START_FLAG_HIST`, `MIN_START_RATE`, `MIN_EXP` |
| Opponent-adjusted statistics | `ADJ_OPP_ALLOWED_RATE` |
| Player archetype matchups | `ARC_POSITION` |
| Potential assists and playmaking | `AST_PCT_ROLL`, `AST_PER_100POSS` |
| Rebound opportunities and conversion | `REB_PCT_ROLL`, `REB_AVAILABLE_MISSES_TEAM` |
| Recent performance and role changes | `FRM_ROLL_RATE`, `FRM_EWMA_RATE`, `FRM_SHRUNK_RATE`, `FRM_PRIOR_SEASON_RATE` |
| Shooting volume and efficiency | `SHT_FG_PCT_SHRUNK`, `SHT_FT_PCT_SHRUNK` |
| Steals, blocks and turnovers | `STL_RATE`, `BLK_RATE`, `TOV_RATE` |
| Team efficiency, possessions and pace | `POS_TEAM_PACE_ROLL`, `POS_MATCHUP_PACE_EXP`, `POS_ONCOURT_FACTOR`, `POS_TEAM_OFF_RTG_ROLL`, `POS_TEAM_DEF_RTG_ROLL` |
| Teammate injuries and availability | `AVL_PLAYED_FLAG_HIST`, `AVL_INACTIVE_LIST_HIST`, `AVL_TEAMMATE_OUT_USAGE` ‡ |
| Three-point shooting | `TPT_3PA_PER_MIN`, `TPT_3PA_RATE`, `TPT_3P_PCT_SHRUNK`, `TPT_OPP_3PA_ALLOWED` |
| Usage and offensive opportunities | `USG_ROLL`, `USG_FGA_PER_MIN`, `USG_FGA_PER_100POSS`, `USG_FTA_RATE` |
| Usage redistribution | `USGR_MINUTES_VACANCY` |

<!-- END:mvp -->
6. **Build first:** (1) ingest + as-of feature store with the season-type/ID/leakage rules; (2) minutes model with the quantile loss; (3) possession and game-environment layer; (4) rate-based baseline per market with NB/binomial distributions; (5) add tracking-opportunity layer via single-day windows; (6) ablation harness; (7) externals. Detail is in the chat summary that accompanied this deliverable.

---

## 10. Regenerating

```bash
python -m venv .venv && .venv/bin/pip install nba_api==1.12.0 pandas numpy
# discovery (network): writes frames + results_*.jsonl
python scripts/discover_endpoints.py <outdir> main      # then: history
python scripts/discover_extra.py <outdir>; python scripts/discover_extra2.py <outdir>
python scripts/qc_checks.py <outdir>/frames data/discovery/qc_results.json
# build + validate (offline): edit definitions in scripts/registry/*.py, then
python scripts/build_artifacts.py   # refuses to write if validation fails
```
