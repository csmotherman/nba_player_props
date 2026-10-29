"""Resumable ingestion. Every API call is logged in source_requests; completed requests are replayed from the raw store."""
import json, logging, uuid
from datetime import datetime, timezone
import pandas as pd

from .. import config
from ..api.client import NBAClient, parse_frames, params_hash
from ..schemas.endpoints import SchemaError
from ..storage.db import upsert
from . import normalize as N, derive

log = logging.getLogger('nba_props.ingest')
PRESEASON_NOTE = 'provisional from id prefix until a game-log request confirms it'


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Ingestor:
    def __init__(self, con, client=None, command='ingest', season=None):
        self.con, self.client = con, client or NBAClient()
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
        self.n_req = self.n_fail = 0
        # DuckDB allows a single writer, so any run still marked 'running' belongs to a process that died without finishing
        con.execute("UPDATE ingestion_runs SET status='abandoned', finished_at=COALESCE(finished_at, ?) WHERE status='running'", [now()])
        con.execute('INSERT INTO ingestion_runs VALUES (?,?,NULL,?,?,?,0,0,NULL)', [self.run_id, now(), command, season, 'running'])

    # ------------------------------------------------------------------ request layer
    def _cached(self, endpoint, params):
        rows = self.con.execute("SELECT raw_path FROM source_requests WHERE endpoint=? AND params_json=? AND ok ORDER BY fetched_at DESC LIMIT 1",
                                [endpoint, json.dumps(params, sort_keys=True)]).fetchall()
        row = rows[0] if rows else None
        if row and row[0]:
            import os
            if os.path.exists(row[0]):
                return row[0]
        return None

    def log_request(self, res, season, rows):
        self.con.execute('INSERT OR REPLACE INTO source_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         [f'{res.endpoint}:{res.params_hash}@{res.fetched_at}', res.endpoint, json.dumps(res.params, sort_keys=True), season, res.ok,
                          res.error, rows, res.sha256, res.raw_path, self.client.api_version, pd.to_datetime(res.fetched_at).tz_localize(None),
                          res.duration_s, res.attempts, self.run_id])
        self.n_req += 1
        self.n_fail += (not res.ok)

    def get(self, endpoint, params, season=None, refresh=False):
        """-> (frames dict, fetched_at) or (None, None). Uses the raw store unless refresh=True."""
        if not refresh:
            path = self._cached(endpoint, params)
            if path:
                fr = parse_frames(endpoint, params, self.client.load_raw(path))
                at = self.con.execute("SELECT max(fetched_at) FROM source_requests WHERE endpoint=? AND params_json=? AND ok",
                                      [endpoint, json.dumps(params, sort_keys=True)]).fetchall()[0][0]
                return fr, at
        res = self.client.fetch(endpoint, params)
        return self._finish(res, season)

    def _safe(self, label, season, fn):
        """Run a normalise+upsert step. A SchemaError (API drift) is logged as a data-quality error and the run continues."""
        try:
            return fn()
        except SchemaError as e:
            log.error('%s: %s', label, e)
            self.n_fail += 1
            self.con.execute('INSERT INTO data_quality_results VALUES (?,?,?,?,?,?,?,?,?)',
                             [now(), 'schema_drift', season, label, 'error', False, str(e), 'required columns present', ''])
            return None

    def _finish(self, res, season):
        if not res.ok:
            self.log_request(res, season, None)
            return None, None
        try:
            fr = parse_frames(res.endpoint, res.params, res.raw)
        except Exception as e:
            res.ok, res.error = False, f'parse: {type(e).__name__}: {e}'
            self.log_request(res, season, None)
            return None, None
        self.log_request(res, season, max([len(d) for d in fr.values()] + [0]))
        return fr, pd.to_datetime(res.fetched_at).tz_localize(None)

    # ------------------------------------------------------------------ core season ingest
    def ingest_season(self, season, season_types=config.DEFAULT_SEASON_TYPES, refresh=False):
        out = {}
        # 1. schedule (pregame-known fields)
        fr, at = self.get('ScheduleLeagueV2', {'season': season}, season, refresh=True if refresh is None else refresh)
        if fr:
            def _sched():
                sch = N.schedule(fr['SeasonGames'], at)
                sch['season'] = season
                sch['in_schedule'] = True
                self._upsert_schedule(sch)
                return len(sch)
            out['schedule_games'] = self._safe('ScheduleLeagueV2', season, _sched)
        for st in season_types:
            # 2. LeagueGameLog (player + team)
            for pt in ('P', 'T'):
                fr, at = self.get('LeagueGameLog', {'season': season, 'player_or_team_abbreviation': pt, 'season_type_all_star': st}, season, refresh)
                if fr is None:
                    continue
                df = fr['LeagueGameLog']
                if len(df) == 0:
                    continue
                out[f'league_{pt}_{st}'] = self._safe(f'LeagueGameLog[{pt}]', season, lambda: upsert(self.con, 'player_game' if pt == 'P' else 'team_game', N.player_game(df, config.SEASON_TYPES[st]) if pt == 'P' else N.team_game(df, config.SEASON_TYPES[st])))
            # 3. PlayerGameLogs / TeamGameLogs (base extras + advanced)
            for mt in ('Base', 'Advanced'):
                fr, at = self.get('PlayerGameLogs', {'season_nullable': season, 'season_type_nullable': st, 'measure_type_player_game_logs_nullable': mt}, season, refresh)
                if fr is not None and len(fr['PlayerGameLogs']):
                    df = fr['PlayerGameLogs']
                    if mt == 'Base':
                        self._safe('PlayerGameLogs[Base]', season, lambda: self._apply_player_extras(N.player_extras(df)))
                    else:
                        out['pgl_adv_' + st] = self._safe('PlayerGameLogs[Advanced]', season, lambda: upsert(self.con, 'player_advanced_game', N.player_advanced(df)))
                fr, at = self.get('TeamGameLogs', {'season_nullable': season, 'season_type_nullable': st, 'measure_type_player_game_logs_nullable': mt}, season, refresh)
                if fr is not None and mt == 'Advanced' and len(fr['TeamGameLogs']):
                    out['tgl_adv_' + st] = self._safe('TeamGameLogs[Advanced]', season, lambda: upsert(self.con, 'team_advanced_game', N.team_advanced(fr['TeamGameLogs'])))
        derive.run(self.con)
        self.con.execute("UPDATE games SET season_type = CASE id_prefix WHEN '001' THEN 'preseason' WHEN '002' THEN 'regular' WHEN '003' THEN 'allstar' "
                         "WHEN '004' THEN 'playoffs' WHEN '005' THEN 'playin' WHEN '006' THEN 'cup_final' END, season_type_source = 'id_prefix_unverified' "
                         "WHERE season_type IS NULL")
        return out

    def _upsert_schedule(self, sch):
        # schedule owns pregame-known fields; never overwrite box-score-derived scores/season_type with NULLs
        have = set(r[0] for r in self.con.execute('SELECT game_id FROM games').fetchall())
        new = sch[~sch.game_id.isin(have)]
        if len(new):
            cols = ['game_id', 'season', 'id_prefix', 'game_date', 'tip_utc', 'home_team_id', 'away_team_id', 'game_status', 'game_label',
                    'game_sub_label', 'game_subtype', 'arena', 'is_neutral', 'in_schedule', 'schedule_fetched_at']
            upsert(self.con, 'games', new, cols)
        old = sch[sch.game_id.isin(have)]
        if len(old):
            self.con.register('_s', old)
            self.con.execute("""UPDATE games g SET season = s.season, id_prefix = s.id_prefix, game_date = s.game_date, tip_utc = s.tip_utc,
                 home_team_id = s.home_team_id, away_team_id = s.away_team_id, game_status = s.game_status, game_label = s.game_label,
                 game_sub_label = s.game_sub_label, game_subtype = s.game_subtype, arena = s.arena, is_neutral = s.is_neutral, in_schedule = TRUE,
                 schedule_fetched_at = s.schedule_fetched_at FROM _s s WHERE g.game_id = s.game_id""")
            self.con.unregister('_s')

    def _apply_player_extras(self, ex):
        self.con.register('_x', ex)
        self.con.execute("UPDATE player_game p SET min_sec = x.min_sec, pfd = x.pfd, blka = x.blka FROM _x x WHERE p.game_id = x.game_id AND p.player_id = x.player_id")
        self.con.unregister('_x')

    # ------------------------------------------------------------------ per-game box scores (starters, inactives)
    def ingest_boxscores(self, season, inactives=True, max_games=None, batch=40):
        games = [r[0] for r in self.con.execute(
            """SELECT game_id FROM games WHERE season=? AND season_type='regular' AND in_gamelog AND game_id NOT IN (SELECT DISTINCT game_id FROM historical_starters)
               ORDER BY game_date, game_id""", [season]).fetchall()]
        todo_inact = []
        if inactives:
            todo_inact = [r[0] for r in self.con.execute(
                """SELECT game_id FROM games WHERE season=? AND season_type='regular' AND in_gamelog AND game_id NOT IN
                   (SELECT DISTINCT game_id FROM historical_inactives)
                   AND game_id NOT IN (SELECT json_extract_string(params_json,'$.game_id') FROM source_requests WHERE endpoint='BoxScoreSummaryV3' AND ok)
                   ORDER BY game_date, game_id""", [season]).fetchall()]
        if max_games:
            games, todo_inact = games[:max_games], todo_inact[:max_games]
        reqs = [('BoxScoreTraditionalV3', {'game_id': g}) for g in games] + [('BoxScoreSummaryV3', {'game_id': g}) for g in todo_inact]
        log.info('%s: %d traditional + %d summary requests', season, len(games), len(todo_inact))
        done = 0
        for i in range(0, len(reqs), batch):                      # commit per batch => interruption loses <= one batch
            for res in self.client.fetch_many(reqs[i:i + batch]):
                fr, at = self._finish(res, season)
                if fr is None:
                    continue
                try:
                    if res.endpoint == 'BoxScoreTraditionalV3':
                        upsert(self.con, 'historical_starters', N.starters(fr['PlayerStats'], at))
                    else:
                        upsert(self.con, 'historical_inactives', N.inactives(fr['InactivePlayers'], at))
                except SchemaError as e:
                    log.error('%s', e)
                done += 1
            log.info('boxscores %s: %d/%d', season, min(i + batch, len(reqs)), len(reqs))
        derive.run(self.con)
        return done

    def finish(self, status='ok', notes=None):
        self.con.execute('UPDATE ingestion_runs SET finished_at=?, status=?, requests=?, failures=?, notes=? WHERE run_id=?',
                         [now(), status, self.n_req, self.n_fail, notes, self.run_id])
