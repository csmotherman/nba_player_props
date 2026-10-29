"""Data-quality checks. Every check returns a structured result and is persisted to data_quality_results.
severity 'error'   = a violated integrity invariant (the warehouse must not be used until resolved)
         'warning' = incomplete coverage / known source inconsistency, quantified, not an invariant violation
         'info'    = measurement"""
import json
from datetime import datetime, timezone
from .. import config

COMPLETE_STATUS = 3


def _r(name, season, source, severity, passed, observed, expected='n/a', details=''):
    return dict(check_name=name, season=season, source=source, severity=severity, passed=bool(passed),
                observed=str(observed), expected=str(expected), details=details if isinstance(details, str) else json.dumps(details, default=str))


def season_checks(con, s):
    q = lambda sql, *a: con.execute(sql, list(a)).fetchall()
    one = lambda sql, *a: con.execute(sql, list(a)).fetchall()[0][0]
    R = []
    # ---- coverage
    sched_done = one("SELECT count(*) FROM games WHERE season=? AND season_type='regular' AND game_status=3", s)
    sched_all = one("SELECT count(*) FROM games WHERE season=? AND season_type='regular' AND in_schedule", s)
    ingested = one("SELECT count(*) FROM games WHERE season=? AND season_type='regular' AND in_gamelog", s)
    complete_season = sched_all == 1230 and sched_done == 1230
    R.append(_r('games_ingested_vs_completed_in_schedule', s, 'ScheduleLeagueV2/LeagueGameLog', 'error', ingested == sched_done, ingested, sched_done,
                f'scheduled regular-season games listed={sched_all}; completed per schedule={sched_done}'))
    R.append(_r('schedule_regular_season_games_listed', s, 'ScheduleLeagueV2', 'warning', sched_all == 1230, sched_all, 1230,
                'A full 82-game season has 1230 games. A shortfall means the schedule listing is INCOMPLETE; no games are inferred or synthesised.'))
    missing_ids = one("""WITH ids AS (SELECT CAST(substr(game_id,6) AS INTEGER) n FROM games WHERE season=? AND id_prefix='002')
                         SELECT count(*) FROM range(1, 1231) r(n) WHERE n NOT IN (SELECT n FROM ids)""", s)
    R.append(_r('regular_season_id_sequence_gaps', s, 'ScheduleLeagueV2', 'info', missing_ids == 0, missing_ids, 0, 'game numbers 1..1230 absent from the schedule listing'))
    teams80 = q("""WITH t AS (SELECT team_id, count(*) n FROM (SELECT home_team_id team_id FROM games WHERE season=? AND id_prefix='002' AND in_schedule
                   UNION ALL SELECT away_team_id FROM games WHERE season=? AND id_prefix='002' AND in_schedule) WHERE team_id IS NOT NULL AND team_id <> '0' GROUP BY 1)
                   SELECT n, count(*) FROM t GROUP BY 1 ORDER BY 1""", s, s)
    R.append(_r('scheduled_games_per_team_distribution', s, 'ScheduleLeagueV2', 'info', all(n == 82 for n, _ in teams80), teams80, '[(82, 30)]',
                'games with unresolved (TBD) team slots are excluded from this per-team count'))
    unresolved = one("SELECT count(*) FROM games WHERE season=? AND id_prefix='002' AND in_schedule AND (home_team_id IS NULL OR away_team_id IS NULL OR home_team_id='0' OR away_team_id='0')", s)
    R.append(_r('schedule_games_with_unresolved_teams', s, 'ScheduleLeagueV2', 'info', unresolved == 0, unresolved, 0))
    # ---- keys and structure
    R.append(_r('player_game_duplicate_keys', s, 'player_game', 'error', one("SELECT count(*) - count(DISTINCT game_id || '|' || player_id) FROM player_game WHERE season=?", s) == 0,
                one("SELECT count(*) - count(DISTINCT game_id || '|' || player_id) FROM player_game WHERE season=?", s), 0))
    bad2 = q("""SELECT game_id, count(*) n, sum(is_home::int) h FROM team_game WHERE season=? AND season_type='regular' GROUP BY 1 HAVING n <> 2 OR h <> 1""", s)
    R.append(_r('exactly_two_teams_one_home_per_game', s, 'team_game', 'error', not bad2, len(bad2), 0, str(bad2[:10])))
    wrong_team = one("""SELECT count(*) FROM team_game t JOIN games g USING(game_id) WHERE t.season=? AND t.team_id NOT IN (g.home_team_id, g.away_team_id) AND g.in_schedule""", s)
    R.append(_r('team_game_team_matches_schedule', s, 'team_game vs games', 'error', wrong_team == 0, wrong_team, 0))
    ptm = one("""SELECT count(*) FROM player_game p JOIN games g USING(game_id) WHERE p.season=? AND g.home_team_id IS NOT NULL AND p.team_id NOT IN (g.home_team_id, g.away_team_id)""", s)
    R.append(_r('player_team_is_one_of_the_two_game_teams', s, 'player_game vs games', 'error', ptm == 0, ptm, 0))
    opp = one("""SELECT count(*) FROM player_game p WHERE p.season=? AND (p.opp_team_id IS NULL OR p.opp_team_id = p.team_id)""", s)
    R.append(_r('player_game_opponent_join', s, 'player_game', 'error', opp == 0, opp, 0))
    orphan_p = one("SELECT count(*) FROM player_game p WHERE p.season=? AND NOT EXISTS (SELECT 1 FROM team_game t WHERE t.game_id=p.game_id AND t.team_id=p.team_id)", s)
    R.append(_r('player_rows_without_team_row', s, 'player_game vs team_game', 'error', orphan_p == 0, orphan_p, 0))
    neutral = one("SELECT count(*) FROM games WHERE season=? AND season_type='regular' AND is_neutral", s)
    mm = one("""SELECT count(*) FROM (SELECT game_id FROM team_game WHERE season=? AND season_type='regular' GROUP BY 1 HAVING sum((matchup LIKE '%vs.%')::int) <> 1)""", s)
    R.append(_r('matchup_home_flag_disagrees_only_on_neutral_sites', s, 'team_game.matchup vs schedule', 'error', mm == neutral or mm <= neutral, f'matchup-ambiguous={mm}, neutral-site games={neutral}', 'equal',
                'MATCHUP reads "@" for both teams at neutral sites; is_home comes from the schedule designation and is_neutral must be used with it'))
    # ---- advanced coverage and cross-source consistency
    n_pg = one("SELECT count(*) FROM player_game WHERE season=?", s)
    n_adv = one("SELECT count(*) FROM player_game p WHERE p.season=? AND EXISTS (SELECT 1 FROM player_advanced_game a WHERE a.game_id=p.game_id AND a.player_id=p.player_id)", s)
    R.append(_r('player_advanced_coverage', s, 'PlayerGameLogs[Advanced]', 'warning', n_adv == n_pg, f'{n_adv}/{n_pg}', 'all rows'))
    adv_orphan = one("SELECT count(*) FROM player_advanced_game a WHERE NOT EXISTS (SELECT 1 FROM player_game p WHERE p.game_id=a.game_id AND p.player_id=a.player_id) AND a.game_id IN (SELECT game_id FROM games WHERE season=?)", s)
    R.append(_r('advanced_rows_without_base_row', s, 'player_advanced_game', 'warning', adv_orphan == 0, adv_orphan, 0))
    for col in ('usg_pct', 'pace', 'poss', 'ts_pct'):
        nn = one(f"SELECT count(*) FROM player_game p JOIN player_advanced_game a USING(game_id, player_id) WHERE p.season=? AND p.min_exact >= 1 AND a.{col} IS NULL", s)
        R.append(_r(f'player_advanced_null_{col}_when_min_ge_1', s, 'player_advanced_game', 'info', True, nn, 'n/a', 'TS_PCT is legitimately NULL with no shot attempts' if col == 'ts_pct' else ''))
    n_t = one("SELECT count(*) FROM team_game WHERE season=?", s); n_ta = one("SELECT count(*) FROM team_game t WHERE t.season=? AND EXISTS (SELECT 1 FROM team_advanced_game a WHERE a.game_id=t.game_id AND a.team_id=t.team_id)", s)
    R.append(_r('team_advanced_coverage', s, 'TeamGameLogs[Advanced]', 'warning', n_t == n_ta, f'{n_ta}/{n_t}', 'all rows'))
    # ---- values
    for col in ('min', 'pts', 'reb', 'ast'):
        R.append(_r(f'player_game_null_{col}', s, 'player_game', 'error', one(f"SELECT count(*) FROM player_game WHERE season=? AND {col} IS NULL", s) == 0, one(f"SELECT count(*) FROM player_game WHERE season=? AND {col} IS NULL", s), 0))
    zero = one("SELECT count(*) FROM player_game WHERE season=? AND min = 0", s)
    R.append(_r('zero_minute_player_rows', s, 'player_game', 'info', True, zero, 'n/a', 'handled: kept as ZERO_MIN appearances, excluded from rolling-history windows'))
    mc = one("SELECT count(*) FROM player_game WHERE season=? AND min_conflict", s)
    R.append(_r('minutes_cross_source_conflict', s, 'LeagueGameLog.MIN vs PlayerGameLogs.MIN_SEC', 'warning', mc == 0, mc, 0, 'player_game.min differs from MIN_SEC by >1 min; min_exact falls back to MIN'))
    # minutes totals: sum of exact player minutes per team-game vs team minutes
    bad_min = q("""WITH x AS (SELECT p.game_id, p.team_id, sum(p.min_exact) s, any_value(t.min) tm FROM player_game p JOIN team_game t USING(game_id, team_id) WHERE p.season=? AND p.season_type='regular' GROUP BY 1,2)
                   SELECT game_id, team_id, round(s,2), tm FROM x WHERE abs(s - tm) > 2.0 ORDER BY abs(s-tm) DESC LIMIT 25""", s)
    nbad = one("""WITH x AS (SELECT sum(p.min_exact) s, any_value(t.min) tm FROM player_game p JOIN team_game t USING(game_id, team_id) WHERE p.season=? AND p.season_type='regular' GROUP BY p.game_id, p.team_id)
                  SELECT count(*) FROM x WHERE abs(s - tm) > 2.0""", s)
    R.append(_r('team_minutes_equal_sum_of_player_minutes', s, 'player_game vs team_game', 'warning', nbad == 0, nbad, 0, 'tolerance 2.0 min (rounding); overtime games use the team MIN (265 = 1 OT, 290 = 2 OT)'))
    otg = q("SELECT min, count(*) FROM team_game WHERE season=? GROUP BY 1 ORDER BY 1", s)
    R.append(_r('team_minutes_distribution_overtime', s, 'team_game', 'info', all(m % 25 == 15 or m == 240 for m, _ in otg), otg, '240 + 25k'))
    # ---- player/team reconciliation (documented exceptions: team TOV)
    for c in ('pts', 'fga', 'ast'):
        bad = one(f"""SELECT count(*) FROM (SELECT sum(p.{c}) a, any_value(t.{c}) b FROM player_game p JOIN team_game t USING(game_id, team_id) WHERE p.season=? GROUP BY p.game_id, p.team_id) WHERE a <> b""", s)
        R.append(_r(f'player_sum_equals_team_{c}', s, 'player_game vs team_game', 'error', bad == 0, bad, 0))
    badtov = one("""SELECT count(*) FROM (SELECT sum(p.tov) a, any_value(t.tov) b FROM player_game p JOIN team_game t USING(game_id, team_id) WHERE p.season=? GROUP BY p.game_id, p.team_id) WHERE a > b""", s)
    R.append(_r('player_tov_sum_not_above_team_tov', s, 'player_game vs team_game', 'error', badtov == 0, badtov, 0, 'documented exception: team turnovers are credited to the team, so player sum <= team'))
    # ---- season type classification (verified, not assumed)
    mism = q("""SELECT season_type, id_prefix, count(*) FROM games WHERE season=? AND in_gamelog AND season_type_source='gamelog_request' AND
                id_prefix <> CASE season_type WHEN 'regular' THEN '002' WHEN 'playoffs' THEN '004' WHEN 'playin' THEN '005' WHEN 'preseason' THEN '001' END GROUP BY ALL""", s)
    R.append(_r('season_type_request_vs_id_prefix', s, 'LeagueGameLog request vs GAME_ID prefix', 'error', not mism, mism, '[]'))
    mixed = q("SELECT season_type, count(*) FROM games WHERE season=? AND in_gamelog GROUP BY 1", s)
    R.append(_r('season_types_present_in_game_logs', s, 'games', 'info', True, mixed, 'regular only by default'))
    cup = q("SELECT game_label, game_subtype, count(*) FROM games WHERE season=? AND id_prefix='002' AND game_subtype LIKE 'in-season%' GROUP BY ALL", s)
    R.append(_r('nba_cup_games_inside_regular_season', s, 'ScheduleLeagueV2', 'info', True, cup, 'n/a', 'Cup group/knockout games carry 002 ids and count as regular season; the Cup final carries 006 and is excluded from regular-season logs'))
    # ---- pregame time information
    notip = one("SELECT count(*) FROM games WHERE season=? AND season_type='regular' AND in_gamelog AND tip_utc IS NULL", s)
    R.append(_r('completed_games_without_tip_time', s, 'ScheduleLeagueV2', 'warning', notip == 0, notip, 0, 'such games fall back to conservative date-based availability'))
    # ---- starters / inactives / appearances
    gdone = one("SELECT count(*) FROM games WHERE season=? AND season_type='regular' AND in_gamelog", s)
    gst = one("SELECT count(DISTINCT game_id) FROM historical_starters WHERE game_id IN (SELECT game_id FROM games WHERE season=?)", s)
    R.append(_r('starters_coverage_games', s, 'BoxScoreTraditionalV3', 'warning', gst == gdone, f'{gst}/{gdone}', 'all completed games'))
    if gst:
        bad5 = one("""SELECT count(*) FROM (SELECT game_id, team_id, sum(started::int) n FROM historical_starters WHERE game_id IN (SELECT game_id FROM games WHERE season=?) GROUP BY 1,2) WHERE n <> 5""", s)
        R.append(_r('exactly_five_starters_per_team', s, 'BoxScoreTraditionalV3', 'error', bad5 == 0, bad5, 0))
        lost = one("""SELECT count(*) FROM historical_starters h JOIN player_game p USING(game_id, player_id) WHERE p.season=? AND h.started AND p.min_exact = 0""", s)
        R.append(_r('starters_with_zero_minutes', s, 'BoxScoreTraditionalV3 vs player_game', 'info', True, lost))
    gin = one("SELECT count(DISTINCT game_id) FROM historical_inactives WHERE game_id IN (SELECT game_id FROM games WHERE season=?)", s)
    ginreq = one("SELECT count(DISTINCT json_extract_string(params_json,'$.game_id')) FROM source_requests WHERE endpoint='BoxScoreSummaryV3' AND ok AND season=?", s)
    R.append(_r('inactives_coverage_games_requested_ok', s, 'BoxScoreSummaryV3', 'warning', ginreq == gdone, f'{ginreq}/{gdone}', 'all completed games', f'games with >=1 inactive row: {gin}'))
    cls = q("""SELECT a.status, a.knowledge_class, count(*) FROM player_appearances a JOIN games g USING(game_id) WHERE g.season=? GROUP BY ALL ORDER BY 1""", s)
    R.append(_r('appearance_status_counts_confirmed_vs_inferred', s, 'player_appearances', 'info', True, cls, 'n/a', 'INFERRED_ABSENT uses games AFTER the target (retrospective); it is never used for pregame features'))
    # ---- requests
    rq = one("SELECT count(*) FROM source_requests WHERE season=?", s); rf = one("SELECT count(*) FROM source_requests WHERE season=? AND NOT ok", s)
    rr = one("SELECT count(*) FROM source_requests WHERE season=? AND attempts > 1", s)
    R.append(_r('api_request_failures', s, 'source_requests', 'warning', rf == 0, f'{rf} failed of {rq} ({rr} needed retries)', 0))
    # ---- features
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='asof_player_features'").fetchone()[0]:
        nf = one("SELECT count(*) FROM asof_player_features WHERE season=?", s)
        dup = one("SELECT count(*) - count(DISTINCT game_id || '|' || player_id || '|' || cutoff_hours) FROM asof_player_features WHERE season=?", s) if nf else 0
        leak = one("SELECT count(*) FROM asof_player_features WHERE season=? AND NOT inputs_available_at_cutoff", s) if nf else 0
        tleak = one("SELECT count(*) FROM asof_team_features WHERE season=? AND NOT inputs_available_at_cutoff", s) if nf else 0
        R.append(_r('asof_features_rows', s, 'asof_player_features', 'info', True, nf))
        R.append(_r('asof_features_duplicate_keys', s, 'asof_player_features', 'error', dup == 0, dup, 0))
        R.append(_r('asof_inputs_available_at_cutoff_violations', s, 'asof_*_features', 'error', leak == 0 and tleak == 0, f'player={leak} team={tleak}', 0))
        low = one("SELECT avg(low_sample_l10::int) FROM asof_player_features WHERE season=? AND cutoff_hours=6", s) if nf else None
        R.append(_r('asof_low_sample_l10_share', s, 'asof_player_features', 'info', True, low))
    return R


def run_all(con, seasons=None):
    seasons = seasons or [r[0] for r in con.execute("SELECT DISTINCT season FROM games WHERE season IS NOT NULL ORDER BY 1").fetchall()]
    res = []
    for s in seasons:
        res += season_checks(con, s)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute("DELETE FROM data_quality_results WHERE season IN (%s)" % ','.join('?' * len(seasons)), seasons)
    for r in res:
        con.execute('INSERT INTO data_quality_results VALUES (?,?,?,?,?,?,?,?,?)', [now, r['check_name'], r['season'], r['source'], r['severity'], r['passed'], r['observed'], r['expected'], r['details']])
    return res


def status(con):
    lines = []
    for t in ('games', 'player_game', 'team_game', 'player_advanced_game', 'team_advanced_game', 'historical_starters', 'historical_inactives', 'player_appearances', 'source_requests'):
        lines.append(f'{t:26s} {con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]:>9,}')
    lines.append('seasons: ' + str(con.execute("SELECT season, season_type, count(*) FILTER (WHERE in_gamelog) FROM games GROUP BY ALL HAVING count(*) FILTER (WHERE in_gamelog) > 0 ORDER BY 1,2").fetchall()))
    lines.append('last runs: ' + str(con.execute("SELECT run_id, command, season, status, requests, failures FROM ingestion_runs ORDER BY started_at DESC LIMIT 5").fetchall()))
    return '\n'.join(lines)
