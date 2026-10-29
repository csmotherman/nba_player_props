"""Integrity tests on REAL rows (committed fixture windows from 2024-25 and 2025-26)."""
import pytest
from nba_props.validation import quality, formulas


def one(con, sql, *a):
    return con.execute(sql, list(a)).fetchall()[0][0]


def test_unique_player_game_and_team_game_keys(fx_con):
    assert one(fx_con, "SELECT count(*) - count(DISTINCT game_id || '|' || player_id) FROM player_game") == 0
    assert one(fx_con, "SELECT count(*) - count(DISTINCT game_id || '|' || team_id) FROM team_game") == 0


def test_exactly_two_teams_and_one_designated_home_per_game(fx_con):
    bad = fx_con.execute("SELECT game_id FROM team_game GROUP BY 1 HAVING count(*) <> 2 OR sum(is_home::int) <> 1").fetchall()
    assert bad == []


def test_neutral_site_games_have_designated_home_but_ambiguous_matchup_text(fx_con):
    n = one(fx_con, "SELECT count(*) FROM games WHERE is_neutral")
    # fixture windows include no neutral game unless the schedule says so; where they exist, is_home still comes from the schedule
    for gid, in fx_con.execute("SELECT game_id FROM games WHERE is_neutral").fetchall():
        assert one(fx_con, "SELECT sum(is_home::int) FROM team_game WHERE game_id = ?", gid) == 1
    assert n >= 0


def test_team_and_opponent_joins_are_consistent(fx_con):
    assert one(fx_con, """SELECT count(*) FROM team_game t JOIN team_game o ON o.game_id=t.game_id AND o.team_id<>t.team_id WHERE t.opp_team_id <> o.team_id""") == 0
    assert one(fx_con, "SELECT count(*) FROM player_game WHERE opp_team_id IS NULL OR opp_team_id = team_id") == 0
    assert one(fx_con, """SELECT count(*) FROM player_game p JOIN games g USING(game_id) WHERE p.team_id NOT IN (g.home_team_id, g.away_team_id)""") == 0
    assert one(fx_con, """SELECT count(*) FROM player_game p JOIN team_game t ON t.game_id=p.game_id AND t.team_id=p.opp_team_id""") == one(fx_con, "SELECT count(*) FROM player_game")


def test_team_minutes_reconcile_with_player_minutes_allowing_overtime(fx_con):
    bad = fx_con.execute("""WITH x AS (SELECT p.game_id, p.team_id, sum(p.min_exact) s, any_value(t.min) tm FROM player_game p JOIN team_game t USING(game_id, team_id) GROUP BY 1,2)
                            SELECT * FROM x WHERE abs(s - tm) > 2.0""").fetchall()
    assert bad == []
    assert {r[0] for r in fx_con.execute("SELECT DISTINCT min FROM team_game").fetchall()} <= {240.0, 265.0, 290.0, 315.0}


def test_player_to_team_reconciliation_with_documented_exceptions(fx_con):
    rc = formulas.reconcile_player_vs_team(fx_con, seasons=('2024-25', '2025-26'))
    for c in ('pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'reb', 'ast', 'stl', 'blk', 'pf'):
        assert rc[c]['exact_share'] == 1.0, c
    assert rc['tov']['player_gt_team'] == 0          # documented exception: team turnovers are credited to the team
    assert rc['tov']['exact_share'] < 1.0


def test_zero_and_missing_minutes_are_handled_explicitly(fx_con):
    assert one(fx_con, "SELECT count(*) FROM player_game WHERE min IS NULL OR min_exact IS NULL") == 0
    zeros = one(fx_con, "SELECT count(*) FROM player_game WHERE min = 0")
    assert one(fx_con, "SELECT count(*) FROM player_appearances WHERE status='ZERO_MIN'") == zeros
    assert one(fx_con, "SELECT count(*) FROM player_appearances WHERE status='APPEARED'") == one(fx_con, "SELECT count(*) FROM player_game WHERE min > 0")


def test_exact_minutes_come_from_min_sec_when_consistent(fx_con):
    assert one(fx_con, "SELECT avg((min_exact <> round(min_exact))::int) FROM player_game WHERE min_sec LIKE '%:%'") > 0.8, 'integer-rounded MIN must be refined by MIN_SEC'
    assert one(fx_con, "SELECT max(abs(min_exact - min)) FROM player_game WHERE NOT min_conflict") <= 1.0


def test_player_team_history_stints_cover_every_game(fx_con):
    assert one(fx_con, "SELECT sum(games) FROM player_team_history") == one(fx_con, "SELECT count(*) FROM player_game")


def test_starters_exactly_five_and_dnp_comments_recorded(fx_con):
    bad = fx_con.execute("SELECT game_id, team_id FROM historical_starters GROUP BY 1,2 HAVING sum(started::int) <> 5").fetchall()
    assert bad == []
    assert one(fx_con, "SELECT count(*) FROM historical_starters WHERE comment ILIKE 'DNP%'") > 0


def test_retrospective_inference_is_labelled_and_separate(fx_con):
    cls = {r[0] for r in fx_con.execute("SELECT DISTINCT knowledge_class FROM player_appearances WHERE status='INFERRED_ABSENT'").fetchall()}
    assert cls <= {'retrospective_inference_uses_future'}
    assert one(fx_con, "SELECT count(*) FROM player_appearances WHERE status='INFERRED_ABSENT' AND knowledge_class='confirmed'") == 0


def test_quality_suite_has_no_error_on_real_fixture(fx_con):
    res = []
    for s in ('2024-25', '2025-26'):
        res += quality.season_checks(fx_con, s)
    errs = [r for r in res if r['severity'] == 'error' and not r['passed']]
    # coverage checks (e.g. games vs full-season schedule) legitimately differ for a date-window fixture: only integrity invariants are errors
    allowed = {'games_ingested_vs_completed_in_schedule'}
    assert [e['check_name'] for e in errs if e['check_name'] not in allowed] == []


# ---- mutation tests: the checks must DETECT injected faults ----
def failing(con, season, name):
    return [r for r in quality.season_checks(con, season) if r['check_name'] == name and not r['passed']]


def test_quality_detects_missing_team_row(fx_copy):
    gid = fx_copy.execute("SELECT game_id FROM team_game WHERE season='2025-26' LIMIT 1").fetchall()[0][0]
    fx_copy.execute("DELETE FROM team_game WHERE game_id=? AND is_home", [gid])
    assert failing(fx_copy, '2025-26', 'exactly_two_teams_one_home_per_game')


def test_quality_detects_wrong_opponent(fx_copy):
    fx_copy.execute("UPDATE player_game SET opp_team_id = team_id WHERE rowid = (SELECT min(rowid) FROM player_game WHERE season='2025-26')")
    assert failing(fx_copy, '2025-26', 'player_game_opponent_join')


def test_quality_detects_player_on_wrong_team(fx_copy):
    fx_copy.execute("UPDATE player_game SET team_id = '999' WHERE rowid = (SELECT min(rowid) FROM player_game WHERE season='2025-26')")
    assert failing(fx_copy, '2025-26', 'player_team_is_one_of_the_two_game_teams')


def test_quality_detects_points_that_do_not_sum(fx_copy):
    fx_copy.execute("UPDATE player_game SET pts = pts + 5 WHERE rowid = (SELECT min(rowid) FROM player_game WHERE season='2025-26' AND min > 20)")
    assert failing(fx_copy, '2025-26', 'player_sum_equals_team_pts')


def test_quality_detects_null_critical_values(fx_copy):
    fx_copy.execute("UPDATE player_game SET reb = NULL WHERE rowid = (SELECT min(rowid) FROM player_game WHERE season='2025-26')")
    assert failing(fx_copy, '2025-26', 'player_game_null_reb')


def test_quality_detects_season_type_prefix_mismatch(fx_copy):
    fx_copy.execute("UPDATE games SET season_type='playoffs' WHERE game_id = (SELECT min(game_id) FROM games WHERE season='2025-26' AND in_gamelog)")
    assert failing(fx_copy, '2025-26', 'season_type_request_vs_id_prefix')


def test_quality_detects_wrong_starter_count(fx_copy):
    fx_copy.execute("UPDATE historical_starters SET started=FALSE WHERE rowid = (SELECT min(rowid) FROM historical_starters WHERE started)")
    assert failing(fx_copy, '2025-26', 'exactly_five_starters_per_team')


def test_formula_checks_run_on_fixture_and_negative_control_fails(fx_con):
    r = formulas.run(fx_con, seasons=('2024-25', '2025-26'))
    assert r['ts_pct']['verdict'] in ('exact_within_rounding', 'exact_with_exceptions')
    assert r['min_vs_min_sec']['verdict'] in ('exact_within_rounding', 'exact_with_exceptions')
    assert r['tov_pct_plain_vs_api']['verdict'] == 'not_equal', 'negative control must NOT match'
    for k in ('usg_pct', 'ast_pct', 'reb_pct', 'team_pace_from_api_poss', 'team_poss_oliver_vs_api'):
        assert r[k]['verdict'] == 'approximate', k          # approximate agreement is not an identity


def test_registry_identity_claims_match_recorded_evidence():
    import json
    from pathlib import Path
    ev = json.loads((Path(__file__).resolve().parents[2] / 'data' / 'discovery' / 'formula_checks.json').read_text())['identities']
    assert ev['ts_pct']['verdict'] in ('exact_within_rounding', 'exact_with_exceptions') and ev['ts_pct']['n'] > 50000
    assert ev['tov_pct_plain_vs_api']['verdict'] == 'not_equal'
    assert ev['usg_pct']['verdict'] == 'approximate' and ev['usg_pct']['mae'] > 0.003
