"""Live-API integration tests. Skipped unless NBA_PROPS_LIVE=1. Few requests, generous pacing: the host throttles bursts."""
import pytest
from nba_props.api.client import NBAClient, parse_frames
from nba_props.storage.db import connect
from nba_props.ingestion.runner import Ingestor

pytestmark = pytest.mark.integration


def test_live_game_log_single_day_matches_schema(tmp_path):
    c = NBAClient(raw_dir=tmp_path, pacing_s=2.0, max_workers=1)
    r = c.fetch('LeagueGameLog', dict(season='2025-26', player_or_team_abbreviation='P', date_from_nullable='2026-01-15', date_to_nullable='2026-01-15'))
    assert r.ok, r.error
    df = parse_frames('LeagueGameLog', r.params, r.raw)['LeagueGameLog']
    assert len(df) > 100 and df.GAME_ID.str.len().eq(10).all()


def test_live_ingest_one_season_into_memory_db(tmp_path):
    con = connect(':memory:')
    ing = Ingestor(con, NBAClient(raw_dir=tmp_path, pacing_s=2.0, max_workers=1), command='live-test')
    ing.ingest_season('2023-24')
    assert con.execute("SELECT count(*) FROM team_game").fetchall()[0][0] == 2460
    assert con.execute("SELECT count(DISTINCT game_id) FROM team_game").fetchall()[0][0] == 1230
