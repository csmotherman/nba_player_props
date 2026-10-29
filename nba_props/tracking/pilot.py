"""OPTIONAL, ISOLATED pilot: do single-day LeagueDashPtStats windows reproduce game-level tracking, and what would a backfill cost?

Reference for every (season, date): LeagueGameLog (player) with the SAME single-day window = independent box-score truth.
Nothing here touches the core warehouse tables; results go to tracking_pilot_results and data/processed/tracking_pilot.json.
"""
import json, statistics
from pathlib import Path
import pandas as pd
from .. import config
from ..api.client import NBAClient, parse_frames
from ..api.guards import require_cutoff

# Representative dates across eras (regular season). Whether a date has games is VERIFIED by the box-score reference, never assumed.
PILOT_DATES = {
    '2013-14': ['2014-01-15', '2014-03-12'], '2016-17': ['2017-01-18', '2017-03-14'], '2019-20': ['2020-01-22', '2020-03-03'],
    '2022-23': ['2023-01-18', '2023-03-08'], '2024-25': ['2025-01-15', '2025-03-12'], '2025-26': ['2026-01-15', '2026-02-25'],
}
EMPTY_DAY = ('2025-26', '2026-02-15')       # All-Star Sunday: no regular-season games expected
MEASURES = {'Passing': ['AST', 'POTENTIAL_AST', 'PASSES_MADE', 'AST_ADJ'], 'Rebounding': ['REB', 'OREB', 'DREB', 'REB_CHANCES'], 'Possessions': ['POINTS', 'TOUCHES', 'TIME_OF_POSS']}
REF_COL = {'Passing': ('AST', 'AST'), 'Rebounding': ('REB', 'REB'), 'Possessions': ('POINTS', 'PTS')}


def window_params(season, d0, d1=None):
    return {'date_from_nullable': d0, 'date_to_nullable': d1 or d0}


def compare(track, box, measure):
    """Pure comparison of a tracking frame with the same-window box-score frame. Returns a dict of verifiable facts."""
    tcol, bcol = REF_COL[measure]
    out = dict(track_rows=int(len(track)), box_rows=int(len(box)))
    if len(track) == 0 or len(box) == 0:
        out.update(match_rate=None, gp_max=None, dup_player_ids=0, only_in_tracking=0, only_in_box=0)
        return out
    t = track.assign(PLAYER_ID=track.PLAYER_ID.astype(str)); b = box.assign(PLAYER_ID=box.PLAYER_ID.astype(str))
    b = b[b.MIN > 0]
    out['dup_player_ids'] = int(t.PLAYER_ID.duplicated().sum())
    out['gp_max'] = int(t.GP.max())
    j = t.merge(b[['PLAYER_ID', bcol, 'MIN']].rename(columns={bcol: 'box_val', 'MIN': 'box_min'}), on='PLAYER_ID', how='inner')
    out['match_rate'] = float((j[tcol] == j['box_val']).mean()) if len(j) else None
    out['abs_err_max'] = float((j[tcol] - j['box_val']).abs().max()) if len(j) else None
    out['only_in_tracking'] = int(len(set(t.PLAYER_ID) - set(b.PLAYER_ID)))
    out['only_in_box'] = int(len(set(b.PLAYER_ID) - set(t.PLAYER_ID)))
    if measure == 'Passing':
        out['potential_ge_assists'] = bool((t.POTENTIAL_AST >= t.AST).all())
    if measure == 'Rebounding':
        out['chances_ge_rebounds'] = bool((t.REB_CHANCES >= t.REB).all())
        out['oreb_dreb_sum_ok'] = bool(((t.OREB + t.DREB) == t.REB).all())
    return out


def window_additivity(a, b, ab, col):
    """Sum over two single-day windows must equal the two-day window (inclusive-boundary semantics)."""
    s = pd.concat([a, b]).groupby(a.PLAYER_ID.name if False else 'PLAYER_ID')[col].sum()
    m = ab.set_index('PLAYER_ID')[col]
    j = pd.concat([s.rename('sum'), m.rename('window')], axis=1).fillna(0)
    return dict(players=int(len(j)), equal_share=float((j['sum'] == j['window']).mean()))


def estimate_cost(latencies, n_seasons=12, dates_per_season=165, n_measures=3, avg_raw_gz_kb=None, pacing_s=None):
    pacing_s = pacing_s or config.PACING_S
    per_req = max(statistics.mean(latencies) if latencies else 1.0, pacing_s)
    n = n_seasons * dates_per_season * n_measures
    return dict(requests=n, hours_at_current_pacing=round(n * per_req / 3600, 2), storage_mb_gz=round(n * (avg_raw_gz_kb or 12) / 1024, 1),
                assumption='~165 distinct game dates per regular season; storage from measured gz size of pilot responses')


class Pilot:
    def __init__(self, client=None, fetch=None):
        self.client = client or NBAClient()
        self.rows, self.lat = [], []
        self._fetch = fetch          # injectable for offline tests: (endpoint, params) -> frames dict | None

    def get(self, endpoint, params):
        if endpoint == 'LeagueDashPtStats':
            require_cutoff(endpoint, params)
        if self._fetch:
            return self._fetch(endpoint, params), 0.0
        res = self.client.fetch(endpoint, params)
        self.lat.append(res.duration_s)
        if not res.ok:
            return None, res.duration_s
        self.last_size = len(open(res.raw_path, 'rb').read()) if res.raw_path else 0
        return parse_frames(endpoint, params, res.raw), res.duration_s

    def box(self, season, d):
        fr, _ = self.get('LeagueGameLog', dict(season=season, player_or_team_abbreviation='P', **{k: v for k, v in window_params(season, d).items()}))
        return None if fr is None else fr['LeagueGameLog']

    def one(self, season, d, measure):
        box = self.box(season, d)
        if box is None:
            return dict(season=season, date=d, measure=measure, ok=False, error='box-score reference request failed')
        fr, dur = self.get('LeagueDashPtStats', dict(season=season, pt_measure_type=measure, player_or_team='Player', per_mode_simple='Totals', **window_params(season, d)))
        if fr is None:
            return dict(season=season, date=d, measure=measure, ok=False, error='tracking request failed', box_rows=int(len(box)))
        track = fr['LeagueDashPtStats']
        r = dict(season=season, date=d, measure=measure, ok=True, duration_s=round(dur, 2), **compare(track, box, measure))
        r['verdict'] = 'no_games_that_day' if r['box_rows'] == 0 and r['track_rows'] == 0 else (
            'empty_tracking_but_games_exist' if r['track_rows'] == 0 else ('exact' if r['match_rate'] == 1.0 and not r['dup_player_ids'] else 'mismatch'))
        return r

    def run(self, dates_per_season=2):
        for season, dates in PILOT_DATES.items():
            for d in dates[:dates_per_season]:
                for m in MEASURES:
                    self.rows.append(self.one(season, d, m))
        self.rows.append(self.one(*EMPTY_DAY, 'Passing'))
        return self.rows

    def semantics(self, season='2025-26', d0='2026-01-14', d1='2026-01-15'):
        """Inclusive boundaries and additivity of windows."""
        a = self.get('LeagueDashPtStats', dict(season=season, pt_measure_type='Passing', player_or_team='Player', per_mode_simple='Totals', **window_params(season, d0)))[0]
        b = self.get('LeagueDashPtStats', dict(season=season, pt_measure_type='Passing', player_or_team='Player', per_mode_simple='Totals', **window_params(season, d1)))[0]
        ab = self.get('LeagueDashPtStats', dict(season=season, pt_measure_type='Passing', player_or_team='Player', per_mode_simple='Totals', **window_params(season, d0, d1)))[0]
        if not (a and b and ab):
            return dict(ok=False, error='request failed')
        A, B, AB = (x['LeagueDashPtStats'] for x in (a, b, ab))
        return dict(ok=True, window=f'{d0}..{d1}', potential_ast=window_additivity(A, B, AB, 'POTENTIAL_AST'), ast=window_additivity(A, B, AB, 'AST'), gp_max_two_day=int(AB.GP.max()))


def run(con, dates_per_season=2, out_path=None):
    p = Pilot()
    rows = p.run(dates_per_season)
    sem = p.semantics()
    ok = [r for r in rows if r.get('ok')]
    summary = dict(requests_ok=len(ok), requests_failed=len(rows) - len(ok), exact=sum(1 for r in ok if r['verdict'] == 'exact'),
                   mismatch=sum(1 for r in ok if r['verdict'] == 'mismatch'), empty_but_games=sum(1 for r in ok if r['verdict'] == 'empty_tracking_but_games_exist'),
                   semantics=sem, cost_estimate=estimate_cost(p.lat), rows=rows)
    out = Path(out_path or config.PROCESSED_DIR / 'tracking_pilot.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, default=str))
    return {k: v for k, v in summary.items() if k != 'rows'}
