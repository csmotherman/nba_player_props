"""Point-in-time feature engine: time semantics, independent recomputation, adversarial leakage scenarios, time-travel."""
import datetime as dt
import numpy as np, pandas as pd, pytest
from nba_props import config
from nba_props.features import asof, cutoffs
from nba_props.validation import timetravel, timesplit
from tests.conftest import load_fixture_db

SEASON, H = '2025-26', 6.0


@pytest.fixture(scope='module')
def built():
    con = load_fixture_db()
    asof.build(con, SEASON, [24, 6, 1])
    return con


# ------------------------------------------------------------------ time semantics
@pytest.mark.parametrize('tip,gd', [(dt.datetime(2025, 10, 22, 2, 0), dt.date(2025, 10, 21)), (None, dt.date(2025, 10, 21))])
def test_python_and_sql_time_definitions_agree(tip, gd):
    import duckdb
    con = duckdb.connect(':memory:')
    t = f"TIMESTAMP '{tip}'" if tip else 'NULL::TIMESTAMP'
    sql_av = con.execute(f"SELECT {cutoffs.sql_available_at(tip=t, gd=repr(str(gd)) + '::DATE')}").fetchone()[0]
    sql_cut = con.execute(f"SELECT {cutoffs.sql_cutoff(6, tip=t, gd=repr(str(gd)) + '::DATE')}").fetchone()[0]
    assert sql_av == cutoffs.available_at(tip, gd) and sql_cut == cutoffs.cutoff_ts(tip, gd, 6)


def test_unknown_tip_is_conservative_in_both_directions():
    d = dt.date(2025, 10, 21)
    # a game on date d with unknown tip is "available" only from d+1 12:00, and a target on d is predicted from d 00:00 minus H
    assert cutoffs.available_at(None, d) == dt.datetime(2025, 10, 22, 12, 0)
    assert cutoffs.cutoff_ts(None, d, 6) == dt.datetime(2025, 10, 20, 18, 0)
    # no real NBA tip on date d (ET) is earlier than 00:00 UTC of d => the fallback cutoff is never later than the true one
    assert cutoffs.cutoff_ts(None, d, 6) <= cutoffs.cutoff_ts(dt.datetime(2025, 10, 21, 20, 0), d, 6)


def test_back_to_back_prior_game_unavailable_at_24h_but_available_at_1h(built):
    row = built.execute("""SELECT game_id, team_id FROM team_game t WHERE season=? AND EXISTS (SELECT 1 FROM asof_team_features f WHERE f.game_id=t.game_id AND f.team_id=t.team_id AND f.is_back_to_back AND f.cutoff_hours=1) LIMIT 1""", [SEASON]).fetchall()
    assert row, 'fixture must contain a back-to-back'
    gid, tid = row[0]
    n = lambda h: built.execute("SELECT n_hist_games FROM asof_team_features WHERE game_id=? AND team_id=? AND cutoff_hours=?", [gid, tid, h]).fetchall()[0][0]
    assert n(24.0) == n(1.0) - 1, 'at 24h before tip the previous night game has not finished'


# ------------------------------------------------------------------ independent pandas recomputation
def pandas_features(con, game_id, player_id, hours):
    pg = con.execute("""SELECT p.game_id, p.player_id, p.team_id, p.game_date, p.season, p.min_exact m, p.pts, p.reb, p.ast, p.fg3a, p.fga, g.tip_utc FROM player_game p JOIN games g USING(game_id)
                        WHERE p.season_type='regular' AND p.player_id=?""", [player_id]).df()
    pg['avail'] = [cutoffs.available_at(None if pd.isna(t) else t.to_pydatetime(), d) for t, d in zip(pg.tip_utc, pg.game_date)]
    tgt = pg[pg.game_id == game_id].iloc[0]
    cut = cutoffs.cutoff_ts(None if pd.isna(tgt.tip_utc) else tgt.tip_utc.to_pydatetime(), tgt.game_date, hours)
    h = pg[(pg.game_id != game_id) & (pg.m > 0) & (pg.avail <= pd.Timestamp(cut))].sort_values(['avail', 'game_id'], ascending=[False, False]).reset_index(drop=True)
    return h, tgt, cut


def test_features_match_independent_pandas_recomputation(built):
    rows = built.execute("""SELECT game_id, player_id FROM asof_player_features WHERE cutoff_hours=? AND n_games_l20 >= 5 ORDER BY hash(game_id || player_id) LIMIT 150""", [H]).fetchall()
    assert len(rows) == 150
    for gid, pid in rows:
        f = built.execute("SELECT * FROM asof_player_features WHERE game_id=? AND player_id=? AND cutoff_hours=?", [gid, pid, H]).df().iloc[0]
        h, tgt, cut = pandas_features(built, gid, pid, H)
        for n in (5, 10, 20):
            w = h.head(n)
            assert f[f'n_games_l{n}'] == len(w)
            assert f[f'min_mean_l{n}'] == pytest.approx(w.m.mean(), abs=1e-9)
            assert f[f'min_median_l{n}'] == pytest.approx(w.m.median(), abs=1e-9)
            if len(w) > 1:
                assert f[f'min_std_l{n}'] == pytest.approx(w.m.std(ddof=1), abs=1e-9)
            for s in ('pts', 'reb', 'ast', 'fg3a', 'fga'):
                assert f[f'{s}_pm_l{n}'] == pytest.approx(w[s].sum() / w.m.sum(), abs=1e-9)
        w = h.head(20); wt = 0.5 ** (np.arange(len(w)) / asof.EWMA_HALF_LIFE_GAMES)
        assert f['min_ewma_l20'] == pytest.approx((w.m * wt).sum() / wt.sum(), abs=1e-9)
        prior = h[h.season == asof.prior_season(SEASON)]
        assert f['prior_season_games'] == len(prior)
        if len(prior) and prior.m.sum() > 0:
            assert f['prior_pts_pm'] == pytest.approx(prior.pts.sum() / prior.m.sum(), abs=1e-9)
        assert f['n_hist_games'] == len(h)
        assert f['max_source_available_at'] == (h.avail.max() if len(h) else pd.NaT) or pd.isna(f['max_source_available_at'])


def test_rest_days_and_back_to_back_match_independent_schedule_computation(built):
    g = built.execute("SELECT game_id, game_date, home_team_id, away_team_id FROM games WHERE season=? AND season_type='regular'", [SEASON]).df()
    long = pd.concat([g[['game_id', 'game_date', 'home_team_id']].rename(columns={'home_team_id': 'team'}), g[['game_id', 'game_date', 'away_team_id']].rename(columns={'away_team_id': 'team'})])
    long = long.sort_values(['team', 'game_date', 'game_id']); long['rest'] = (long.groupby('team').game_date.diff().dt.days - 1)
    f = built.execute("SELECT game_id, team_id, rest_days, is_back_to_back FROM asof_team_features WHERE cutoff_hours=?", [H]).df().merge(long, left_on=['game_id', 'team_id'], right_on=['game_id', 'team'])
    both = f.dropna(subset=['rest'])
    assert (both.rest_days == both.rest).all() and (both.is_back_to_back == (both.rest == 0)).all()
    assert f[f.rest.isna()].rest_days.isna().all(), 'season openers have unknown rest, not zero'


def test_team_rolling_environment_matches_pandas(built):
    t = built.execute("""SELECT a.game_id, a.team_id, a.poss, a.min, a.off_rating, a.def_rating, g.tip_utc, g.game_date FROM team_advanced_game a JOIN games g USING(game_id) JOIN team_game x ON x.game_id=a.game_id AND x.team_id=a.team_id WHERE x.season_type='regular'""").df()
    t['avail'] = [cutoffs.available_at(None if pd.isna(a) else a.to_pydatetime(), d) for a, d in zip(t.tip_utc, t.game_date)]
    for gid, tid in built.execute("SELECT game_id, team_id FROM asof_team_features WHERE cutoff_hours=? AND n_games_l10 = 10 ORDER BY hash(game_id||team_id) LIMIT 40", [H]).fetchall():
        f = built.execute("SELECT * FROM asof_team_features WHERE game_id=? AND team_id=? AND cutoff_hours=?", [gid, tid, H]).df().iloc[0]
        me = t[(t.game_id == gid) & (t.team_id == tid)].iloc[0]
        cut = cutoffs.cutoff_ts(None if pd.isna(me.tip_utc) else me.tip_utc.to_pydatetime(), me.game_date, H)
        h = t[(t.team_id == tid) & (t.game_id != gid) & (t.avail <= pd.Timestamp(cut))].sort_values(['avail', 'game_id'], ascending=False).head(10)
        assert f.pace_l10 == pytest.approx(48 * h.poss.sum() / h['min'].sum(), abs=1e-9)
        assert f.poss_l10 == pytest.approx(h.poss.mean(), abs=1e-9)
        assert f.off_rating_l10 == pytest.approx((h.off_rating * h.poss).sum() / h.poss.sum(), abs=1e-9)


def test_starter_rate_uses_only_covered_games(built):
    r = built.execute("SELECT start_rate_l10, start_games_covered_l10, n_games_l10 FROM asof_player_features WHERE cutoff_hours=? AND start_games_covered_l10 > 0 LIMIT 500", [H]).df()
    assert len(r) and r.start_rate_l10.between(0, 1).all() and (r.start_games_covered_l10 <= r.n_games_l10).all()
    none = built.execute("SELECT missing_starter_info FROM asof_player_features WHERE cutoff_hours=? AND (start_games_covered_l10 = 0 OR start_games_covered_l10 IS NULL) LIMIT 5", [H]).fetchall()
    assert all(x[0] for x in none), 'unsupported starter history must be flagged missing, not zero'


# ------------------------------------------------------------------ adversarial leakage scenarios
def feat(con, hours=H, game_date=None):
    cols = [c[0] for c in con.execute('DESCRIBE asof_player_features').fetchall() if c[0] != 'limitations']
    q = f"SELECT {','.join(cols)} FROM asof_player_features WHERE season=? AND cutoff_hours=?" + (" AND game_date=?" if game_date else '') + " ORDER BY game_id, player_id"
    return con.execute(q, [SEASON, float(hours)] + ([game_date] if game_date else [])).df()


def test_label_columns_never_appear_among_features(built):
    cols = {c[0] for c in built.execute('DESCRIBE asof_player_features').fetchall()}
    assert not {'pts', 'reb', 'ast', 'fg3a', 'fga', 'min', 'min_exact', 'fg3m', 'stl', 'blk', 'tov', 'plus_minus'} & cols
    assert not [c for c in cols if c.startswith('label_')]
    assert {c[0] for c in built.execute('DESCRIBE v_training_examples').fetchall()} >= {'label_pts', 'label_min'}


def test_poisoning_the_target_game_changes_nothing(built):
    """Direct target-label leakage / rolling windows including the target game."""
    con = load_fixture_db(); asof.build(con, SEASON, [H]); base = feat(con)
    d = con.execute("SELECT game_date FROM games WHERE season=? AND in_gamelog ORDER BY game_date OFFSET 40 LIMIT 1", [SEASON]).fetchall()[0][0]
    con.execute("UPDATE player_game SET pts=999, reb=999, ast=999, fga=999, fg3a=999, min=48, min_exact=48 WHERE game_date=? AND season=?", [d, SEASON])
    con.execute("UPDATE team_advanced_game SET poss=999, off_rating=999, def_rating=999 WHERE game_id IN (SELECT game_id FROM games WHERE game_date=?)", [d])
    asof.build(con, SEASON, [H])
    after = feat(con)
    mine = base.game_date == pd.Timestamp(d)
    pd.testing.assert_frame_equal(base[mine].reset_index(drop=True), after[mine].reset_index(drop=True))
    # whereas the NEXT days legitimately see the poisoned history (so the test is not vacuous)
    nxt = (base.game_date > pd.Timestamp(d)) & (base.game_date <= pd.Timestamp(d) + pd.Timedelta(days=3))
    assert not base[nxt].reset_index(drop=True).equals(after[nxt].reset_index(drop=True))


def test_future_dated_rows_do_not_change_historical_features(built):
    """Future-dated joins and 'models using results from future dates'."""
    con = load_fixture_db(); asof.build(con, SEASON, [H]); base = feat(con)
    cut = con.execute("SELECT game_date FROM games WHERE season=? AND in_gamelog ORDER BY game_date OFFSET 80 LIMIT 1", [SEASON]).fetchall()[0][0]
    for t in ('player_game', 'team_game'):
        con.execute(f"UPDATE {t} SET pts = pts * 7 WHERE game_date > ?", [cut])
    con.execute("UPDATE team_advanced_game SET poss = 1 WHERE game_id IN (SELECT game_id FROM games WHERE game_date > ?)", [cut])
    asof.build(con, SEASON, [H]); after = feat(con)
    early = base.game_date <= pd.Timestamp(cut)
    pd.testing.assert_frame_equal(base[early].reset_index(drop=True), after[early].reset_index(drop=True))


def test_future_roster_information_is_ignored(built):
    """A player whose first appearance for a team is AFTER the target must not be on that target's pregame roster."""
    con = load_fixture_db(); asof.build(con, SEASON, [H])
    base = con.execute("SELECT game_id, team_id, player_id, eligible FROM asof_roster_eligibility WHERE cutoff_hours=? ORDER BY 1,2,3", [H]).df()
    late = con.execute("""SELECT p.player_id, p.team_id, min(p.game_date) first_d FROM player_game p WHERE p.season=? AND p.min_exact>0 GROUP BY 1,2
                          HAVING first_d > (SELECT min(game_date) FROM games WHERE season=?) + INTERVAL 10 DAY ORDER BY first_d LIMIT 1""", [SEASON, SEASON]).fetchall()
    assert late, 'fixture needs a player who joins a team late'
    pid, tid, first = late[0]
    ghost = con.execute("SELECT count(*) FROM asof_roster_eligibility r JOIN games g USING(game_id) WHERE r.player_id=? AND r.team_id=? AND g.game_date <= ? AND r.cutoff_hours=?", [pid, tid, first, H]).fetchall()[0][0]
    assert ghost == 0, 'a player must not be in the pregame roster before his first appearance for the team'
    # moving his FUTURE appearance earlier/later must not alter earlier rosters
    con.execute("UPDATE player_game SET game_date = game_date + INTERVAL 30 DAY WHERE player_id=? AND team_id=? AND game_date >= ?", [pid, tid, first])
    asof.build(con, SEASON, [H])
    after = con.execute("SELECT game_id, team_id, player_id, eligible FROM asof_roster_eligibility WHERE cutoff_hours=? ORDER BY 1,2,3", [H]).df()
    ids = con.execute("SELECT game_id FROM games WHERE game_date < ?", [first]).df().game_id
    pd.testing.assert_frame_equal(base[base.game_id.isin(ids)].reset_index(drop=True), after[after.game_id.isin(ids)].reset_index(drop=True))


def test_pregame_roster_never_reads_retrospective_inference():
    con = load_fixture_db(); asof.build(con, SEASON, [H])
    base = con.execute("SELECT count(*), sum(eligible::int) FROM asof_roster_eligibility WHERE cutoff_hours=?", [H]).fetchall()[0]
    con.execute("DELETE FROM player_appearances WHERE status='INFERRED_ABSENT'")
    con.execute("UPDATE player_appearances SET knowledge_class='tampered'")
    asof.build(con, SEASON, [H])
    assert con.execute("SELECT count(*), sum(eligible::int) FROM asof_roster_eligibility WHERE cutoff_hours=?", [H]).fetchall()[0] == base


def test_unknown_completion_timestamps_same_date_games_are_excluded():
    """Same-date games when tip/completion times are unknown: nothing from the same or previous calendar day may be used."""
    con = load_fixture_db()
    con.execute("UPDATE games SET tip_utc = NULL")
    asof.build(con, SEASON, [H])
    r = con.execute("SELECT count(*) bad FROM asof_player_features WHERE cutoff_hours=? AND max_source_game_date >= game_date - INTERVAL 1 DAY", [H]).fetchall()[0][0]
    assert r == 0, 'conservative mode must exclude same-day AND previous-day games when completion time is unknown'
    assert con.execute("SELECT bool_and(NOT tip_known) FROM asof_player_features").fetchall()[0][0]
    assert con.execute("SELECT count(*) FROM asof_player_features WHERE NOT inputs_available_at_cutoff").fetchall()[0][0] == 0
    know = load_fixture_db(); asof.build(know, SEASON, [H])
    a = con.execute("SELECT sum(n_games_l10) FROM asof_player_features WHERE cutoff_hours=?", [H]).fetchall()[0][0]
    b = know.execute("SELECT sum(n_games_l10) FROM asof_player_features WHERE cutoff_hours=?", [H]).fetchall()[0][0]
    assert a < b, 'with unknown tips the engine must use LESS history, never more'


def test_every_row_provenance_is_available_at_its_cutoff(built):
    assert built.execute("SELECT count(*) FROM asof_player_features WHERE NOT inputs_available_at_cutoff OR max_source_available_at > cutoff_ts").fetchall()[0][0] == 0
    assert built.execute("SELECT count(*) FROM asof_team_features WHERE NOT inputs_available_at_cutoff OR max_source_available_at > cutoff_ts").fetchall()[0][0] == 0
    assert built.execute("SELECT count(*) FROM asof_player_features WHERE max_source_game_date >= game_date").fetchall()[0][0] == 0


def test_explain_lists_only_sources_available_before_cutoff(built):
    gid, pid = built.execute("SELECT game_id, player_id FROM asof_player_features WHERE cutoff_hours=? AND n_games_l20=20 LIMIT 1", [H]).fetchall()[0]
    e = asof.explain(built, gid, pid, H)
    assert e['inputs_available_at_cutoff'] and all(s['ok'] for s in e['last20_sources']) and len(e['last20_sources']) == 20
    assert all(s['available_at'] <= e['cutoff_ts'] for s in e['last20_sources']) and e['max_source_available_at'] <= e['cutoff_ts']


def test_cutoffs_are_monotone_more_history_with_earlier_prediction_never(built):
    a = built.execute("""SELECT f24.game_id, f24.player_id, f24.n_hist_games n24, f1.n_hist_games n1 FROM asof_player_features f24 JOIN asof_player_features f1
                         ON f1.game_id=f24.game_id AND f1.player_id=f24.player_id AND f1.cutoff_hours=1 WHERE f24.cutoff_hours=24""").df()
    assert (a.n24 <= a.n1).all(), 'a later cutoff can only add history'


# ------------------------------------------------------------------ chronological split guard
def test_training_results_from_future_dates_are_rejected():
    now = pd.Timestamp('2025-11-10 20:00')
    test = pd.DataFrame({'cutoff_ts': [now, now + pd.Timedelta(hours=3)]})
    ok = pd.DataFrame({'label_available_at': [now - pd.Timedelta(days=2), now - pd.Timedelta(hours=1)]})
    assert timesplit.assert_chronological(ok, test)
    bad = pd.DataFrame({'label_available_at': [now - pd.Timedelta(days=2), now + pd.Timedelta(minutes=1)]})
    with pytest.raises(timesplit.ChronologyError):
        timesplit.assert_chronological(bad, test)


def test_purged_walk_forward_never_trains_on_unavailable_labels(built):
    ex = built.execute("""SELECT f.game_id, f.player_id, f.cutoff_ts, a.available_at label_available_at FROM asof_player_features f JOIN game_avail a USING(game_id) WHERE f.cutoff_hours=?""", [H]).df()
    n = 0
    for tr, te in timesplit.purged_walk_forward(ex, 4):
        assert ex.loc[tr, 'label_available_at'].max() <= ex.loc[te, 'cutoff_ts'].min()
        n += 1
    assert n == 4


# ------------------------------------------------------------------ the time-travel test
@pytest.mark.parametrize('offset', [30, 80, 140, 200])
def test_time_travel_features_unchanged_when_later_data_is_added(offset):
    con = load_fixture_db()
    d = con.execute("SELECT DISTINCT game_date FROM games WHERE season=? AND in_gamelog ORDER BY 1 OFFSET ? LIMIT 1", [SEASON, offset // 10]).fetchall()[0][0]
    res = timetravel.time_travel(con, SEASON, d, hours=6)
    assert res['n_rows'] > 100, res
    assert res['mismatching_columns'] == [], res


def test_time_travel_detects_a_deliberately_leaky_feature():
    """Sanity check of the test itself: an engine that peeked at later data would be caught."""
    con = load_fixture_db()
    d = con.execute("SELECT DISTINCT game_date FROM games WHERE season=? AND in_gamelog ORDER BY 1 OFFSET 8 LIMIT 1", [SEASON]).fetchall()[0][0]
    early = timetravel.clone(con, up_to_date=d); full = timetravel.clone(con)
    f1 = timetravel.snapshot_features(early, SEASON, 6, d)
    full.execute("UPDATE player_game SET min_exact = min_exact + 3 WHERE game_date = ?", [d])          # alter the TARGET day only in the full copy
    full.execute("UPDATE player_game SET min_exact = min_exact + 3 WHERE game_date > ?", [d])
    f2 = timetravel.snapshot_features(full, SEASON, 6, d)
    assert timetravel.compare(f1, f2)[1] == [], 'altering target/future rows must not change features (control)'
    # but altering PAST rows does change them, i.e. the comparison has teeth
    full2 = timetravel.clone(con); full2.execute("UPDATE player_game SET min_exact = min_exact + 3 WHERE game_date < ?", [d])
    f3 = timetravel.snapshot_features(full2, SEASON, 6, d)
    assert timetravel.compare(f1, f3)[1] != []
