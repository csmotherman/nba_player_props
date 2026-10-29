"""Expected response schemas. A missing required column is a hard SchemaError (API drift must be loud)."""
REQUIRED = {
    'LeagueGameLog': {'SEASON_ID', 'TEAM_ID', 'GAME_ID', 'GAME_DATE', 'MATCHUP', 'MIN', 'PTS', 'FGA', 'FG3A', 'REB', 'AST'},
    'PlayerGameLogs': {'PLAYER_ID', 'TEAM_ID', 'GAME_ID', 'GAME_DATE', 'MATCHUP', 'MIN'},
    'TeamGameLogs': {'TEAM_ID', 'GAME_ID', 'GAME_DATE', 'MATCHUP', 'MIN'},
    'ScheduleLeagueV2': {'gameId', 'gameDateEst', 'gameDateTimeUTC', 'gameStatus', 'homeTeam_teamId', 'awayTeam_teamId'},
    'BoxScoreTraditionalV3': {'gameId', 'teamId', 'personId', 'position', 'comment', 'minutes'},
    'BoxScoreSummaryV3': {'gameId', 'teamId', 'personId'},   # checked on the InactivePlayers set
}
ADVANCED_PLAYER = {'USG_PCT', 'PACE', 'POSS', 'TS_PCT', 'AST_PCT', 'REB_PCT'}
ADVANCED_TEAM = {'POSS', 'PACE', 'OFF_RATING', 'DEF_RATING'}


class SchemaError(ValueError):
    pass


def check(name, columns, required=None):
    missing = (required or REQUIRED[name]) - set(columns)
    if missing:
        raise SchemaError(f'{name}: missing columns {sorted(missing)}')
