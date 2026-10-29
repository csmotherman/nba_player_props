"""Execution-time leakage guards for the NBA client. Metadata validation (registry) is NOT a substitute for these."""

# Season-aggregate endpoints return data through *today* unless bounded; using them for a past target leaks the future.
SEASON_AGGREGATE_ENDPOINTS = {
    'LeagueDashPlayerStats', 'LeagueDashTeamStats', 'LeagueDashPtStats', 'LeagueDashPlayerPtShot', 'LeagueDashTeamPtShot', 'LeagueDashOppPtShot',
    'LeagueDashPtDefend', 'LeagueDashPtTeamDefend', 'LeagueDashPlayerShotLocations', 'LeagueDashTeamShotLocations', 'LeagueDashLineups',
    'LeagueHustleStatsPlayer', 'LeagueHustleStatsTeam', 'TeamPlayerOnOffSummary', 'TeamPlayerOnOffDetails', 'PlayerDashboardByGeneralSplits',
    'PlayerDashboardByLastNGames', 'LeagueDashPlayerClutch', 'SynergyPlayTypes', 'GravityLeaders', 'LeagueStandingsV3', 'CommonTeamRoster', 'PlayerIndex',
}
CURRENT_SNAPSHOT_ONLY = {'LeagueStandingsV3', 'CommonTeamRoster', 'PlayerIndex', 'GravityLeaders', 'SynergyPlayTypes'}   # no date filter exists


class LeakageGuardError(ValueError):
    pass


def require_cutoff(endpoint, params, as_of_required=True):
    """Raise unless a season-aggregate request is bounded by date_to (the day BEFORE the prediction date).
    Snapshot-only endpoints cannot be bounded at all and are refused for historical use."""
    if not as_of_required or endpoint not in SEASON_AGGREGATE_ENDPOINTS:
        return
    if endpoint in CURRENT_SNAPSHOT_ONLY:
        raise LeakageGuardError(f'{endpoint} only serves the current snapshot; it cannot be used for a historical as-of feature')
    if not params.get('date_to_nullable'):
        raise LeakageGuardError(f'{endpoint} without date_to_nullable returns season-to-date through today and leaks the future')
