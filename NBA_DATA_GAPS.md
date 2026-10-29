# NBA Data Gaps, External Sources, Substitutes and Limitations

Companion to `NBA_DATA_BLUEPRINT.md`. Evidence for every statement is in `data/discovery/` (raw results) and `NBA_API_ENDPOINT_INVENTORY.csv`. "Not available" means *not found in nba_api 1.12.0 as of 2026-10-29*, not that it does not exist elsewhere.

## 1. Gap summary

| # | Gap | Why it matters | Severity | Best nba_api substitute | External source required |
|---|---|---|---|---|---|
| 1 | Pregame injury report / player status | Largest single driver of minutes and usage redistribution | **Critical** | Realised absences (`InactivePlayers`, appearances) for training only | Yes |
| 2 | Prop lines, prices, line movement (live and historical) | Needed to measure edge; strongest single predictor | **Critical** | None | Yes |
| 3 | Historical spreads / totals / moneylines | Blowout risk, game environment calibration | High | Team-rating spread proxy (`BLO_RATING_SPREAD_PROXY`) | Yes |
| 4 | Confirmed / expected starters (pregame) | Minutes and role | High | `MIN_START_PROB_TODAY` from history | Yes |
| 5 | Official rotations / on-court lineups | On-court missed shots, true lineup features, garbage time | High | Parse `PlayByPlayV3` substitutions (UNVERIFIED) | No (if recon works) |
| 6 | Pregame officials | Foul / free-throw environment | Low-Med | None | Yes |
| 7 | Pregame defender assignments | Matchup-aware features | Low-Med | Team-level DvP, archetype DvP | Possibly |
| 8 | Minute restrictions, return timelines, news | Returns from injury, ramp-up | Medium | `MIN_RETURN_RAMP` (lagged) | Yes |
| 9 | Travel distance, time zones, altitude | Fatigue, rest quality | Low | Rest days, back-to-back flags | Static table |
| 10 | Point-in-time standings, rosters, coaches | Motivation, role-change context | Low | Rebuild from game results | No |
| 11 | Fine-grained position / role labels | DvP, archetypes | Medium | Data-driven clusters (`ARC_CLUSTER_ID`) | No |
| 12 | Tracking history before 2013-14 and hustle before 2016-17 | Long training histories for opportunity features | Medium | Rate-based baseline features | No |

## 2. Missing data in detail

### 2.1 Injury and availability (gap 1)
* **Findings.** None of the 142 library endpoints is an injury report. `PlayerNextNGames` returned 0 rows for three requests. `BoxScoreSummaryV3.InactivePlayers` returns the inactive list for completed games (11 rows in the sample game) but was **empty for an unplayed game about 4.5 hours before tip (probed 15:28 EDT, tip 20:00 EDT)** (2026-10-29, game `0022600144`), as was `Officials`. Whether and when it fills before tip-off is unverified.
* **Consequence.** Training can use realised inactives; serving cannot without an external feed. Using realised inactives in training and an uncertain pregame status at serving creates train/serve skew: backtests will look better than live performance unless statuses are reconstructed as they stood at the prediction cutoff.
* **Required external schema.** `player_id, team_id, game_id, status {Out, Doubtful, Questionable, Probable, Available, GTD}, reason, source, snapshot_ts`. Keep every snapshot; map status to start/play probabilities empirically per status and hours-to-tip.
* **Candidate source types** (none verified, licensing/terms not assessed): the league's own published injury report; commercial injury/news feeds.

### 2.2 Prop lines and odds (gap 2) and game lines (gap 3)
* **Findings.** `nba_api.live.nba.endpoints.Odds` returned 33 games with markets `2way` (moneyline) and `spread` only, from several books (Novibet, TabAustralia, FanDuel, bwin.ES, Mozzartbet in our run), each with opening and current price and spread. **No totals and no player props.** It is a snapshot; nothing historical is served.
* **Consequence.** No way to compute edge, closing-line value or calibrated blowout risk from history without an external dataset. The prop line itself is the best single feature; whether to include it is a modelling decision (Blueprint section 7).
* **Required external schema.** `book, market, player_id, line, over_price, under_price, open_line, open_ts, snapshot_ts, closing flag`; for games `spread, total, moneyline` with timestamps.
* **Cheap mitigation now.** Start snapshotting the live `Odds` endpoint daily to build a spread/moneyline history going forward.

### 2.3 Starters (gap 4)
* **Findings.** Starters are derivable for completed games (`BoxScoreTraditionalV3.position` non-empty, 20/20 sampled games exactly five per team). The live `BoxScore` for the unplayed game returned an empty body and `BoxScoreTraditionalV3` for it raised an error; lineup availability close to tip-off was not tested.
* **To test:** poll the live box score and `ScoreboardV3` in the hour before tip-off to see when starters appear.

### 2.4 Rotation and lineups (gap 5)
* **Findings.** `GameRotation` failed with `JSONDecodeError` in all ten tests (nine eras and 2025-26). `PlayByPlayV3` returns substitution events (`actionType="Substitution"`, text "SUB: X FOR Y") but starting lineups per period are not explicit, so on-court intervals must be inferred.
* **Consequence.** True on-court missed shots, garbage-time filtering and exact lineup features are blocked until reconstruction is validated (`MIN_ROTATION_RECON`, UNVERIFIED). Interim: minutes-proportional approximation, flagged as an unsupported assumption.
* **Acceptance test.** Reconstructed player minutes within 1 minute of box `MIN` for >95% of player-games across at least three seasons.

### 2.5 Officials, defenders, news, geo (gaps 6-9)
* Officials exist historically (3 per completed game in `BoxScoreSummaryV3.Officials`) but were empty pregame when checked. League assignments are normally published on game day; availability through nba_api is unverified.
* Defender assignments exist after the game (`BoxScoreMatchupsV3`, 2017-18+); nothing predicts them pregame.
* News/minute restrictions need an external feed and text parsing.
* Arena city/state are in `ScheduleLeagueV2`; coordinates, altitude and time zone need a static table.

### 2.6 Point-in-time context (gap 10)
`LeagueStandingsV3` and `CommonTeamRoster` (including coaches) return the current table only. `CTX_STANDINGS_MOTIVATION` and `ROLE_COACH_CHANGE` must be rebuilt from game results; coach change dates are not exposed.

## 3. Partially available: depth or timing unverified

| Item | Tested | Not tested |
|---|---|---|
| `PlayerGameLogs`, `TeamGameLogs` | 2025-26, 2026-27 | Everything earlier (`LeagueGameLog` covers box columns historically) |
| Single-day tracking windows (potential assists, rebound chances) | 2026-01-15 (Passing) | Other dates/seasons, Rebounding/Possessions/Drives windows, depth to 2013-14 |
| `BoxScoreSummaryV3` historical inactives/officials | One 2025-26 game | Earlier seasons |
| `SynergyPlayTypes` | 2014-15..2017-18, 2025-26 | 2013-14 and earlier; date filters |
| `LeagueDashPtDefend` | 2013-14..2015-16, 2025-26 | 2012-13 |
| `PlayerEstimatedMetrics` | 2012-13, 2013-14, 2025-26 | Earlier |
| `LeagueDashLineups` | 2007-08, 2012-13, 2025-26 | Row cap of exactly 2000; completeness |
| Hustle | 2014-15 (empty), 2015-16 (147), 2016-17+ | Why 2015-16 is partial |
| `ScheduleLeagueV2` | 2025-26, 2026-27 | Earlier seasons; 2026-27 returned 1,206 `002` ids vs 1,230 expected |
| All other season-level dashboards | 2025-26 | Earlier seasons, `date_to` on most |
| Sustained throughput / rate limits | ~440 calls, 3 threads | Multi-thousand-call backfills |

## 4. Required external sources: minimum viable set

| Priority | Source | Used by | Blocks |
|---|---|---|---|
| 1 | Injury/status feed with timestamps | `EXT_INJURY_REPORT`, `AVL_TEAMMATE_OUT_USAGE`, `AVL_OPP_KEY_PLAYER_OUT`, `USGR_*`, `MIN_EXP` | Serving; honest backtest of availability effects |
| 2 | Player-prop odds with history | `EXT_PROP_LINES` | Edge/CLV evaluation, market-aware modelling |
| 3 | Game spreads/totals with history | `BLO_SPREAD_HISTORICAL`, `BLO_PROB_BLOWOUT` upgrade | Calibrated blowout risk |
| 4 | Confirmed starters | `EXT_CONFIRMED_STARTERS` | Late minutes updates |
| 5 | Officials, geodata, news | `HOP_REF_CREW_FOUL_RATE`, `CTX_TRAVEL_GEO`, `EXT_NEWS_TRANSACTIONS` | Secondary features |

## 5. Possible substitutes and their cost

| Missing | Substitute | Cost / risk |
|---|---|---|
| Injury feed | Realised absences from `InactivePlayers` + appearances; poll `InactivePlayers` near tip if it populates | Train/serve skew; late inactives only; timing unverified |
| Confirmed starters | `MIN_START_PROB_TODAY` from start history and teammate absence | Misses coach decisions; uncertainty kept in the minutes mixture |
| Historical spreads | `BLO_RATING_SPREAD_PROXY` from net ratings + fitted home term | Wider error than market; validate RMSE before use |
| Rotation chart | PBP substitution parse | Period-start lineups must be inferred; accuracy unknown |
| On-court missed shots | Minutes-proportional misses | Smears garbage time and lineup effects |
| Defender assignment | Team-level + archetype DvP | Loses individual matchup effects |
| Position detail | Cluster-based archetypes | Cluster names/stability to be validated |
| Hustle/tracking before 2016-17 / 2013-14 | Drop those features for early seasons; train opportunity models on 2013-14+ only | Shorter history; two feature regimes |

## 6. Limitations

* **Unofficial, undocumented API.** Endpoints can be removed or change shape (V2 box scores, `PlayByPlayV2` already did; `GameRotation`, `DefenseHub`, `TeamDashPtShots`, `WinProbabilityPBP` failed). Pin the library version, snapshot raw responses, monitor row counts, and expect breakage.
* **Coverage claims are limited to tested seasons** (see section 3 and per-feature `historical_availability`). Anything between sampled seasons is assumed, not verified.
* **Tracking and hustle are only as old as their introduction** and may differ in definition across years; compare distributions across seasons before pooling.
* **Position buckets are coarse** (G/F/C) and listed, not played, positions.
* **Result-set names from the library are sometimes misaligned**; always map by column signature.
* **Statistical corrections.** Box scores can be revised after the game; store fetch timestamps and re-fetch recent games.
* **Small samples.** Opponent-specific, teammate-pair and matchup features have very few observations; they require heavy shrinkage and may not survive ablation.
* **Rankings are hypotheses.** No feature has been tested for predictive value.

## 7. Open tests (ordered, with pass criteria)

1. **Pregame timing of `InactivePlayers` / `Officials` / live `BoxScore`.** Poll an upcoming game every 10 min from the morning of game day (the first probe, 4.5 h before tip, found them empty); record when each fills. Pass: usable at the intended cutoff.
2. **Single-day tracking windows at scale.** For 20 random dates in each of 2013-14, 2016-17, 2019-20, 2022-23, 2024-25: do `AST` totals match game logs (>=99%)? Check Rebounding, Possessions, Drives.
3. **`LeagueDashLineups` cap.** Compare `sum(MIN)` by team to expected team minutes; compare with `TeamDashLineups` counts.
4. **`PlayerGameLogs`/`TeamGameLogs` history depth** for 2015-16 through 2024-25.
5. **`opponent_team_id` semantics.** Reconcile summed lines vs team `OPP_*` totals for one team/date.
6. **`TeamGameLogs[Opponent]` column ownership** (which team's steals/blocks/turnovers `OPP_STL`, `OPP_BLK`, `OPP_TOV` represent) on one game.
7. **`TIME_OF_POSS` unit.**
8. **PBP rotation reconstruction** against box minutes (section 2.4).
9. **Why four endpoints fail** (`GameRotation`, `DefenseHub`, `TeamDashPtShots`, `WinProbabilityPBP`): retry across days/headers; check parameters.
10. **Starter flag cheaper path:** `LeagueDashPlayerStats(starter_bench_nullable='Starters')` single-day windows vs `BoxScoreTraditionalV3`.
11. **Sustained backfill throughput**: one full season of per-game calls with backoff; measure error rate.
12. **2026-27 schedule completeness** (1,206 vs 1,230 regular-season ids) and whether later additions appear.
13. **`SynergyPlayTypes` date filters** and 2013-14 availability.
14. **Historical `BoxScoreSummaryV3`** inactives/officials for 2015-16..2024-25.
15. **Historical injury-status reconstruction** feasibility from an external source (timestamps at 24 h / 3 h / 90 min before tip).
