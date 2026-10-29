"""Real-data leakage and correctness audit (run against the actual warehouse). Results feed NBA_DATA_QUALITY_REPORT.md."""
import numpy as np, pandas as pd
from ..features import asof, cutoffs
from . import timetravel


def scan(con, season):
    q = lambda sql, *a: con.execute(sql, list(a)).fetchall()[0]
    r = dict(rows=q("SELECT count(*) FROM asof_player_features WHERE season=?", season)[0])
    if not r['rows']:
        return r
    r['available_at_cutoff_violations'] = q("SELECT count(*) FROM asof_player_features WHERE season=? AND (NOT inputs_available_at_cutoff OR max_source_available_at > cutoff_ts)", season)[0]
    r['team_available_at_cutoff_violations'] = q("SELECT count(*) FROM asof_team_features WHERE season=? AND (NOT inputs_available_at_cutoff OR max_source_available_at > cutoff_ts)", season)[0]
    r['history_game_not_before_target'] = q("SELECT count(*) FROM asof_player_features WHERE season=? AND max_source_game_date >= game_date", season)[0]
    r['duplicate_keys'] = q("SELECT count(*) - count(DISTINCT game_id||'|'||player_id||'|'||cutoff_hours) FROM asof_player_features WHERE season=?", season)[0]
    r['tip_unknown_rows'] = q("SELECT count(*) FROM asof_player_features WHERE season=? AND NOT tip_known", season)[0]
    r['max_source_available_at'] = str(q("SELECT max(max_source_available_at) FROM asof_player_features WHERE season=?", season)[0])
    return r


def independent_recompute(con, season, hours, n=2000, seed=11):
    """Recompute rolling features for n sampled rows in pandas from the raw tables and compare."""
    rows = con.execute("SELECT game_id, player_id FROM asof_player_features WHERE season=? AND cutoff_hours=? AND n_games_l5 >= 1 ORDER BY hash(game_id||player_id||?) LIMIT ?",
                       [season, float(hours), str(seed), n]).fetchall()
    ids = sorted({r[1] for r in rows})
    pg = con.execute(f"""SELECT p.game_id, p.player_id, p.game_date, p.season, p.min_exact m, p.pts, p.reb, p.ast, p.fg3a, p.fga, g.tip_utc
                         FROM player_game p JOIN games g USING(game_id) WHERE p.season_type='regular' AND p.player_id IN ({','.join('?' * len(ids))})""", ids).df()
    pg['avail'] = [cutoffs.available_at(None if pd.isna(t) else t.to_pydatetime(), d) for t, d in zip(pg.tip_utc, pg.game_date)]
    by = {k: v for k, v in pg.groupby('player_id')}
    feat = con.execute("SELECT * FROM asof_player_features WHERE season=? AND cutoff_hours=?", [season, float(hours)]).df().set_index(['game_id', 'player_id'])
    bad, checked = [], 0
    for gid, pid in rows:
        f = feat.loc[(gid, pid)]
        d = by[pid]; t = d[d.game_id == gid].iloc[0]
        cut = pd.Timestamp(cutoffs.cutoff_ts(None if pd.isna(t.tip_utc) else t.tip_utc.to_pydatetime(), t.game_date, hours))
        h = d[(d.game_id != gid) & (d.m > 0) & (d.avail <= cut)].sort_values(['avail', 'game_id'], ascending=False)
        for w in (5, 10, 20):
            x = h.head(w)
            exp = {f'n_games_l{w}': len(x), f'min_mean_l{w}': x.m.mean(), f'pts_pm_l{w}': x.pts.sum() / x.m.sum() if x.m.sum() else np.nan, f'ast_pm_l{w}': x.ast.sum() / x.m.sum() if x.m.sum() else np.nan}
            for k, v in exp.items():
                if not (pd.isna(v) and pd.isna(f[k])) and abs(float(f[k]) - float(v)) > 1e-9:
                    bad.append((gid, pid, k, float(f[k]), float(v)))
        checked += 1
    return dict(rows_checked=checked, mismatches=len(bad), first_mismatches=bad[:5])


def poison_test(con, season, hours, game_date):
    """Alter the TARGET day's box scores in a clone: features for that day must be unchanged."""
    clone = timetravel.clone(con)
    base = timetravel.snapshot_features(clone, season, hours, game_date)
    clone.execute("UPDATE player_game SET pts=999, reb=999, ast=999, fga=999, fg3a=999, min_exact=48 WHERE game_date=?", [game_date])
    clone.execute("UPDATE team_advanced_game SET poss=999, off_rating=999 WHERE game_id IN (SELECT game_id FROM games WHERE game_date=?)", [game_date])
    after = timetravel.snapshot_features(clone, season, hours, game_date)
    n, bad = timetravel.compare(base, after)
    clone.close()
    return dict(game_date=str(game_date), rows=n, mismatching_columns=bad)


def unknown_tip_test(con, season, hours):
    clone = timetravel.clone(con)
    clone.execute("UPDATE games SET tip_utc = NULL")
    asof.build(clone, season, [hours])
    r = clone.execute("SELECT count(*), sum((max_source_game_date >= game_date - INTERVAL 1 DAY)::int), sum((NOT inputs_available_at_cutoff)::int) FROM asof_player_features WHERE season=? AND cutoff_hours=?", [season, float(hours)]).fetchall()[0]
    known = con.execute("SELECT sum(n_games_l10) FROM asof_player_features WHERE season=? AND cutoff_hours=?", [season, float(hours)]).fetchall()[0][0]
    unk = clone.execute("SELECT sum(n_games_l10) FROM asof_player_features WHERE season=? AND cutoff_hours=?", [season, float(hours)]).fetchall()[0][0]
    clone.close()
    return dict(rows=int(r[0]), same_or_previous_day_history_rows=int(r[1] or 0), availability_violations=int(r[2] or 0), history_games_known_tip=float(known), history_games_unknown_tip=float(unk))


def roster_quality(con, season, hours):
    """How well does the strictly-pregame roster (built only from information available at the cutoff) cover who actually played?"""
    q = lambda sql: con.execute(sql, [season, float(hours)]).fetchall()[0]
    played = q("SELECT count(*) FROM player_game WHERE season=? AND season_type='regular' AND min_exact>0 AND ? = ?")[0] if False else \
        con.execute("SELECT count(*) FROM player_game WHERE season=? AND season_type='regular' AND min_exact > 0", [season]).fetchall()[0][0]
    hit = con.execute("""SELECT count(*) FROM asof_roster_eligibility WHERE season=? AND cutoff_hours=? AND eligible AND label_actually_played""", [season, float(hours)]).fetchall()[0][0]
    elig = con.execute("SELECT count(*) FROM asof_roster_eligibility WHERE season=? AND cutoff_hours=? AND eligible", [season, float(hours)]).fetchall()[0][0]
    missed = con.execute("""SELECT count(*) FROM player_game p WHERE p.season=? AND p.season_type='regular' AND p.min_exact > 0 AND NOT EXISTS
                            (SELECT 1 FROM asof_roster_eligibility r WHERE r.game_id=p.game_id AND r.player_id=p.player_id AND r.cutoff_hours=? AND r.eligible)""", [season, float(hours)]).fetchall()[0][0]
    never = con.execute("""SELECT count(*) FROM player_game p WHERE p.season=? AND p.season_type='regular' AND p.min_exact > 0 AND NOT EXISTS
                           (SELECT 1 FROM asof_roster_eligibility r WHERE r.game_id=p.game_id AND r.player_id=p.player_id AND r.cutoff_hours=?)""", [season, float(hours)]).fetchall()[0][0]
    return dict(actual_participants=int(played), eligible_pregame=int(elig), eligible_and_played=int(hit), participants_missing_from_pregame_roster=int(missed),
                of_which_never_seen_for_team_before=int(never), recall=hit / played if played else None, precision=hit / elig if elig else None, hours=hours)


def run_all(con, seasons, hours=6.0, tt_dates_per_season=4):
    out = dict(seasons=seasons, cutoff_hours=hours, scan={}, independent={}, time_travel=[], poison=[], roster={}, unknown_tip={})
    for s in seasons:
        out['scan'][s] = scan(con, s)
        if out['scan'][s]['rows']:
            out['independent'][s] = independent_recompute(con, s, hours, n=1500)
            out['roster'][s] = roster_quality(con, s, hours)
            dates = [str(r[0]) for r in con.execute("SELECT DISTINCT game_date FROM games WHERE season=? AND in_gamelog AND game_date >= (SELECT min(game_date) FROM games WHERE season=? AND in_gamelog) + INTERVAL 30 DAY ORDER BY 1", [s, s]).fetchall()]
            picks = [dates[int(len(dates) * q)] for q in (0.1, 0.4, 0.7, 0.95)][:tt_dates_per_season] if dates else []
            for d in picks:
                out['time_travel'].append(dict(season=s, **timetravel.time_travel(con, s, d, hours)))
            if picks:
                out['poison'].append(dict(season=s, **poison_test(con, s, hours, picks[1])))
    s0 = seasons[-2] if len(seasons) > 1 else seasons[0]
    out['unknown_tip'] = dict(season=s0, **unknown_tip_test(con, s0, hours))
    return out
