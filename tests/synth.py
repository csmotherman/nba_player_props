"""SYNTHETIC mini-league used ONLY for edge cases real fixture windows cannot isolate (trades, call-ups, rookies, season boundary).
Every value is deterministic. Nothing here is evidence about real NBA data."""
import datetime as dt
import pandas as pd
from nba_props.storage.db import connect
from nba_props.ingestion import derive

TEAMS = ['1', '2', '3', '4']


def build(days=40, start=dt.date(2025, 11, 1), season='2025-26', prefix='00225', moves=None, prior=False, rookies=None, dnp=None, con=None, first_seq=1):
    """moves: {player: [(first_day_idx, team)]}; rookies: {player: first_day_idx}; dnp: {(player, day_idx)}."""
    con = con or connect(':memory:')
    g, tg, pg, ta = [], [], [], []
    base = {p: t for t in TEAMS for p in [f'p{t}{k}' for k in range(1, 7)]}
    moves = moves or {}; rookies = rookies or {}; dnp = dnp or set()
    seq = first_seq
    for i in range(days):
        d = start + dt.timedelta(days=i)
        pairs = [('1', '2'), ('3', '4')] if i % 2 == 0 else [('1', '3'), ('2', '4')]
        for home, away in pairs:
            gid = f'{prefix}{seq:05d}'; seq += 1
            tip = dt.datetime(d.year, d.month, d.day, 23, 0)             # 23:00 UTC = 7pm ET
            g.append(dict(game_id=gid, season=season, season_type='regular', season_type_source='gamelog_request', id_prefix=prefix[:3], game_date=d, tip_utc=tip,
                          home_team_id=home, away_team_id=away, game_status=3, in_schedule=True, in_gamelog=True, is_neutral=False))
            for team, opp, is_home in ((home, away, True), (away, home, False)):
                tg.append(dict(game_id=gid, team_id=team, opp_team_id=opp, is_home=is_home, game_date=d, season=season, season_type='regular', matchup='x', wl='W', min=240.0,
                               fgm=40, fga=85, fg3m=12, fg3a=33, ftm=15, fta=20, oreb=10, dreb=33, reb=43, ast=24, stl=7, blk=5, tov=13, pf=19, pts=100 + i, plus_minus=0.0,
                               team_abbreviation=f'T{team}', team_name=f'Team {team}'))
                ta.append(dict(game_id=gid, team_id=team, min=48.0, poss=95 + (i % 7), pace=95.0 + (i % 7), off_rating=110.0 + i % 5, def_rating=108.0 + i % 3))
                for pl in _roster(team, i, base, moves, rookies):
                    k = int(pl[-1]) if pl[-1].isdigit() else 3
                    m = 0.0 if (pl, i) in dnp else 36.0 - 3 * (k % 6)
                    pg.append(dict(game_id=gid, player_id=pl, team_id=team, opp_team_id=opp, is_home=is_home, game_date=d, season=season, season_type='regular', matchup='x', wl='W',
                                   min=float(round(m)), min_sec=f'{int(m)}:00', fgm=5, fga=10 + k, fg3m=1, fg3a=3, ftm=2, fta=3, oreb=1, dreb=4, reb=5 + k % 3, ast=2 + k % 4, stl=1, blk=0, tov=2, pf=2,
                                   pts=10 + k + i % 5, plus_minus=0.0, player_name=pl, min_exact=m, min_conflict=False))
    for name, rows in (('games', g), ('team_game', tg), ('player_game', pg), ('team_advanced_game', ta)):
        con.register('_s', pd.DataFrame(rows)); con.execute(f'INSERT INTO {name} BY NAME SELECT * FROM _s'); con.unregister('_s')
    derive.run(con)
    return con


def _roster(team, day, base, moves, rookies):
    out = []
    for p, t in base.items():
        cur = t
        for first, to in sorted(moves.get(p, [])):
            if day >= first: cur = to
        if cur == team and day >= rookies.get(p, 0):
            out.append(p)
    for p, mv in moves.items():
        if p not in base:                               # players that exist only through moves
            cur = None
            for first, to in sorted(mv):
                if day >= first: cur = to
            if cur == team: out.append(p)
    return out
