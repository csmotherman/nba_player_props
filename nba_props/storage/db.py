"""DuckDB warehouse: schema, connection and idempotent upserts. All NBA ids are VARCHAR (leading zeros matter)."""
import duckdb
from .. import config

DDL = """
CREATE TABLE IF NOT EXISTS teams(team_id VARCHAR PRIMARY KEY, abbreviation VARCHAR, name VARCHAR, first_seen_date DATE, last_seen_date DATE);
CREATE TABLE IF NOT EXISTS players(player_id VARCHAR PRIMARY KEY, name VARCHAR, first_game_date DATE, last_game_date DATE, games INTEGER);
CREATE TABLE IF NOT EXISTS games(
  game_id VARCHAR PRIMARY KEY, season VARCHAR, season_type VARCHAR, season_type_source VARCHAR, id_prefix VARCHAR,
  game_date DATE, tip_utc TIMESTAMP, home_team_id VARCHAR, away_team_id VARCHAR, game_status INTEGER,
  home_score INTEGER, away_score INTEGER, game_label VARCHAR, game_sub_label VARCHAR, game_subtype VARCHAR, arena VARCHAR, is_neutral BOOLEAN,
  in_schedule BOOLEAN DEFAULT FALSE, in_gamelog BOOLEAN DEFAULT FALSE, schedule_fetched_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS player_game(
  game_id VARCHAR, player_id VARCHAR, team_id VARCHAR, opp_team_id VARCHAR, is_home BOOLEAN, game_date DATE, season VARCHAR, season_type VARCHAR,
  matchup VARCHAR, wl VARCHAR, min DOUBLE, min_sec VARCHAR, fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
  oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER, pts INTEGER, plus_minus DOUBLE,
  pfd INTEGER, blka INTEGER, player_name VARCHAR, min_exact DOUBLE, min_conflict BOOLEAN, PRIMARY KEY(game_id, player_id));
CREATE TABLE IF NOT EXISTS team_game(
  game_id VARCHAR, team_id VARCHAR, opp_team_id VARCHAR, is_home BOOLEAN, game_date DATE, season VARCHAR, season_type VARCHAR, matchup VARCHAR, wl VARCHAR,
  min DOUBLE, fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER, oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER,
  stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER, pts INTEGER, plus_minus DOUBLE, team_abbreviation VARCHAR, team_name VARCHAR, PRIMARY KEY(game_id, team_id));
CREATE TABLE IF NOT EXISTS player_advanced_game(
  game_id VARCHAR, player_id VARCHAR, team_id VARCHAR, min DOUBLE, poss INTEGER, pace DOUBLE, e_pace DOUBLE, usg_pct DOUBLE, e_usg_pct DOUBLE,
  ts_pct DOUBLE, efg_pct DOUBLE, ast_pct DOUBLE, reb_pct DOUBLE, oreb_pct DOUBLE, dreb_pct DOUBLE, tm_tov_pct DOUBLE, pie DOUBLE,
  off_rating DOUBLE, def_rating DOUBLE, net_rating DOUBLE, PRIMARY KEY(game_id, player_id));
CREATE TABLE IF NOT EXISTS team_advanced_game(
  game_id VARCHAR, team_id VARCHAR, min DOUBLE, poss INTEGER, pace DOUBLE, e_pace DOUBLE, off_rating DOUBLE, def_rating DOUBLE, net_rating DOUBLE,
  efg_pct DOUBLE, ts_pct DOUBLE, tm_tov_pct DOUBLE, oreb_pct DOUBLE, dreb_pct DOUBLE, reb_pct DOUBLE, ast_pct DOUBLE, pie DOUBLE, PRIMARY KEY(game_id, team_id));
CREATE TABLE IF NOT EXISTS player_team_history(player_id VARCHAR, team_id VARCHAR, stint_start DATE, stint_end DATE, games INTEGER, stint_no INTEGER, PRIMARY KEY(player_id, stint_no));
CREATE TABLE IF NOT EXISTS player_appearances(
  game_id VARCHAR, player_id VARCHAR, team_id VARCHAR, status VARCHAR, knowledge_class VARCHAR, status_source VARCHAR, comment VARCHAR,
  PRIMARY KEY(game_id, player_id, status));
CREATE TABLE IF NOT EXISTS historical_starters(game_id VARCHAR, player_id VARCHAR, team_id VARCHAR, started BOOLEAN, position VARCHAR, comment VARCHAR, minutes_str VARCHAR, fetched_at TIMESTAMP, PRIMARY KEY(game_id, player_id));
CREATE TABLE IF NOT EXISTS historical_inactives(game_id VARCHAR, team_id VARCHAR, player_id VARCHAR, first_name VARCHAR, family_name VARCHAR, fetched_at TIMESTAMP, PRIMARY KEY(game_id, player_id));
CREATE TABLE IF NOT EXISTS source_requests(
  request_id VARCHAR PRIMARY KEY, endpoint VARCHAR, params_json VARCHAR, season VARCHAR, ok BOOLEAN, error VARCHAR, rows INTEGER,
  response_sha256 VARCHAR, raw_path VARCHAR, nba_api_version VARCHAR, fetched_at TIMESTAMP, duration_s DOUBLE, attempts INTEGER, run_id VARCHAR);
CREATE TABLE IF NOT EXISTS ingestion_runs(run_id VARCHAR PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP, command VARCHAR, season VARCHAR, status VARCHAR, requests INTEGER, failures INTEGER, notes VARCHAR);
CREATE TABLE IF NOT EXISTS data_quality_results(checked_at TIMESTAMP, check_name VARCHAR, season VARCHAR, source VARCHAR, severity VARCHAR, passed BOOLEAN, observed VARCHAR, expected VARCHAR, details VARCHAR);
"""


def connect(path=None, read_only=False):
    path = str(path or config.DB_PATH)
    if path != ':memory:':
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
    con = duckdb.connect(path, read_only=read_only)
    if not read_only:
        con.execute(DDL)
        for tbl, col, typ in (('player_game', 'min_exact', 'DOUBLE'), ('player_game', 'min_conflict', 'BOOLEAN'), ('games', 'is_neutral', 'BOOLEAN')):
            con.execute(f'ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {typ}')   # migrations for databases created before these existed
    return con


PKS = {'teams': ['team_id'], 'players': ['player_id'], 'games': ['game_id'], 'player_game': ['game_id', 'player_id'], 'team_game': ['game_id', 'team_id'],
       'player_advanced_game': ['game_id', 'player_id'], 'team_advanced_game': ['game_id', 'team_id'], 'historical_starters': ['game_id', 'player_id'],
       'historical_inactives': ['game_id', 'player_id'], 'player_appearances': ['game_id', 'player_id', 'status']}


def upsert(con, table, df, cols=None):
    """Idempotent upsert: ON CONFLICT updates ONLY the columns supplied, so a source that provides a subset of a table's
    columns can be re-ingested without wiping columns owned by another source. Returns rows written."""
    if df is None or len(df) == 0:
        return 0
    cols = cols or list(df.columns)
    pk = PKS[table]
    sets = ', '.join(f'{c} = excluded.{c}' for c in cols if c not in pk)
    con.register('_up', df[cols])
    try:
        con.execute(f'INSERT INTO {table}({",".join(cols)}) SELECT {",".join(cols)} FROM _up ON CONFLICT ({",".join(pk)}) DO UPDATE SET {sets}')
    finally:
        con.unregister('_up')
    return len(df)
