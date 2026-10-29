"""Tests against the REAL local warehouse (skipped on a fresh clone). Run after `python -m nba_props ingest ...`."""
import pytest
from nba_props.storage.db import connect
from nba_props.validation import quality

pytestmark = pytest.mark.realdata


@pytest.fixture(scope='module')
def con():
    return connect(read_only=True)


def test_completed_seasons_are_complete(con):
    for s in ('2023-24', '2024-25', '2025-26'):
        assert con.execute("SELECT count(*) FROM games WHERE season=? AND season_type='regular' AND in_gamelog", [s]).fetchall()[0][0] == 1230
        assert con.execute("SELECT count(*) FROM team_game WHERE season=?", [s]).fetchall()[0][0] == 2460


def test_no_error_severity_failures(con):
    errs = [r for s in ('2023-24', '2024-25', '2025-26', '2026-27') for r in quality.season_checks(con, s) if r['severity'] == 'error' and not r['passed']]
    assert errs == [], [e['check_name'] for e in errs]


def test_features_exist_and_are_leak_free(con):
    for s in ('2024-25', '2025-26'):
        assert con.execute("SELECT count(*) FROM asof_player_features WHERE season=? AND (NOT inputs_available_at_cutoff OR max_source_available_at > cutoff_ts)", [s]).fetchall()[0][0] == 0
