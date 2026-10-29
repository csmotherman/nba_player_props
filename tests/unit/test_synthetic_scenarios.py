"""SYNTHETIC edge cases (labelled): trades, call-ups, rookies, missing prior season, season boundary, missing advanced rows."""
import datetime as dt
import pandas as pd, pytest
from nba_props.features import asof
from tests.synth import build


def feats(con, season='2025-26', hours=6.0):
    asof.build(con, season, [hours])
    return con.execute("SELECT * FROM asof_player_features WHERE cutoff_hours=?", [hours]).df()


def row(f, player, day, start=dt.date(2025, 11, 1)):
    d = pd.Timestamp(start + dt.timedelta(days=day))
    r = f[(f.player_id == player) & (f.game_date == d)]
    assert len(r) == 1, (player, day)
    return r.iloc[0]


def test_traded_player_first_game_with_new_team_is_flagged_not_hidden():
    con = build(moves={'pX': [(0, '1'), (20, '2')]}, days=40)          # SYNTHETIC: pX plays for team 1, traded to team 2 before day 20
    f = feats(con)
    first_new = f[(f.player_id == 'pX') & (f.team_id == '2')].sort_values('game_date').iloc[0]
    assert first_new.asof_team_id == '1' and first_new.team_changed_vs_last
    assert first_new.games_with_team_asof == first_new.n_hist_games > 0          # whole history is with the old team
    later = f[(f.player_id == 'pX') & (f.team_id == '2')].sort_values('game_date').iloc[1]
    assert later.asof_team_id == '2' and not later.team_changed_vs_last and later.games_with_team_asof == 1 and later.team_changes_365d == 1


def test_trade_does_not_put_player_on_new_teams_pregame_roster_until_he_has_played_for_them():
    con = build(moves={'pX': [(0, '1'), (20, '2')]}, days=40)
    asof.build(con, '2025-26', [6.0])
    first_new = con.execute("SELECT min(game_date) FROM player_game WHERE player_id='pX' AND team_id='2'").fetchall()[0][0]
    r = con.execute("SELECT eligible FROM asof_roster_eligibility r JOIN games g USING(game_id) WHERE r.player_id='pX' AND r.team_id='2' AND g.game_date=?", [first_new]).fetchall()
    assert r == [], 'a traded-in player is unknown to the new team until his first appearance (recall < 1 is reported, not hidden)'
    old = con.execute("SELECT eligible FROM asof_roster_eligibility r JOIN games g USING(game_id) WHERE r.player_id='pX' AND r.team_id='1' AND g.game_date>?", [first_new]).fetchall()
    assert all(not e[0] for e in old) and old, 'old team must drop him once his latest appearance is for another team'


def test_player_moving_a_to_b_to_a_counts_two_changes():
    con = build(moves={'pY': [(0, '3'), (6, '4'), (10, '3')]}, days=30)
    f = feats(con)
    r = row(f, 'pY', 14)
    assert r.team_changes_365d == 2 and r.asof_team_id == '3' and not r.team_changed_vs_last
    stints = con.execute("SELECT team_id, games FROM player_team_history WHERE player_id='pY' ORDER BY stint_no").fetchall()
    assert [s[0] for s in stints] == ['3', '4', '3']


def test_rookie_has_no_history_and_is_flagged():
    con = build(days=30, rookies={'p21': 12})
    f = feats(con)
    r = f[(f.player_id == 'p21')].sort_values('game_date').iloc[0]
    assert r.n_hist_games == 0 and r.no_history_in_warehouse and r.low_sample_l5 and pd.isna(r.min_mean_l5) and pd.isna(r.pts_pm_l10) and r.no_prior_season
    assert not r.inputs_available_at_cutoff is False


def test_early_season_windows_fill_progressively():
    con = build(days=20)
    f = feats(con)
    n = [row(f, 'p11', d).n_games_l5 for d in range(1, 8)]
    assert n == sorted(n) and n[0] < 5 and n[-1] == 5
    assert row(f, 'p11', 3).low_sample_l5 and not row(f, 'p11', 9).low_sample_l5 and row(f, 'p11', 9).low_sample_l10


def test_missing_prior_season_is_null_and_flagged_not_zero():
    con = build(days=15)
    r = row(feats(con), 'p11', 10)
    assert r.no_prior_season and r.prior_season_games == 0 and pd.isna(r.prior_pts_pm)


def test_season_boundary_prior_season_values_and_std_reset():
    con = build(days=30, start=dt.date(2025, 3, 1), season='2024-25', prefix='00224')
    build(days=10, start=dt.date(2025, 11, 1), season='2025-26', prefix='00225', con=con)
    f = feats(con)
    r = f[(f.player_id == 'p11')].sort_values('game_date').iloc[0]                      # first game of 2025-26
    assert r.prior_season_games == 30 and r.std_games == 0
    assert r.prior_pts_pm > 0 and r.n_games_l20 == 20 and r.days_since_last_game > 200
    second = f[(f.player_id == 'p11')].sort_values('game_date').iloc[1]
    assert second.std_games == 1 and second.prior_season_games == 30
    prior_pts = con.execute("SELECT sum(pts)/sum(min_exact) FROM player_game WHERE player_id='p11' AND season='2024-25'").fetchall()[0][0]
    assert r.prior_pts_pm == pytest.approx(prior_pts)


def test_zero_minute_rows_do_not_enter_rolling_windows():
    con = build(days=25, dnp={('p11', d) for d in (10, 12, 14)})
    f = feats(con)
    r = row(f, 'p11', 20)
    played = con.execute("SELECT count(*) FROM player_game WHERE player_id='p11' AND min_exact>0 AND game_date < DATE '2025-11-21'").fetchall()[0][0]
    assert r.n_hist_games == played == 17        # 20 team games before day 20, minus 3 zero-minute rows
    assert con.execute("SELECT count(*) FROM player_appearances WHERE player_id='p11' AND status='ZERO_MIN'").fetchall()[0][0] == 3


def test_missing_team_advanced_row_reduces_sample_and_is_flagged():
    con = build(days=25)
    victim = con.execute("SELECT game_id FROM games WHERE game_date = DATE '2025-11-10' LIMIT 1").fetchall()[0][0]
    hit = [r[0] for r in con.execute("SELECT team_id FROM team_advanced_game WHERE game_id=?", [victim]).fetchall()]
    con.execute("DELETE FROM team_advanced_game WHERE game_id=? AND team_id=?", [victim, hit[0]])
    asof.build(con, '2025-26', [6.0])
    r = con.execute("""SELECT team_id, n_games_l10, low_sample_l10, pace_l10 FROM asof_team_features WHERE cutoff_hours=6 AND game_date = DATE '2025-11-11'
                       AND team_id IN (%s) ORDER BY team_id""" % ','.join("'%s'" % h for h in hit)).fetchall()
    by = {x[0]: x for x in r}
    assert by[hit[0]][1] == 9 and by[hit[0]][2] is True, 'the team missing one advanced row has a 9-game sample, flagged low'
    assert by[hit[0]][3] is not None, 'pace is computed from the remaining games, never zero-filled'
    assert by[hit[1]][1] == 10 and by[hit[1]][2] is False


def test_rest_days_and_back_to_back_synthetic_schedule():
    con = build(days=12)       # every team plays every day => rest_days 0 except the opener
    asof.build(con, '2025-26', [6.0])
    r = con.execute("SELECT min(rest_days), max(rest_days), sum(missing_rest_days::int), count(*) FROM asof_team_features WHERE cutoff_hours=6").fetchall()[0]
    assert r[0] == 0 and r[1] == 0 and r[2] == 4 and r[3] == 48
