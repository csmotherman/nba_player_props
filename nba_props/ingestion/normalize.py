"""Pure DataFrame normalisers: API frame -> warehouse rows. No I/O, no network; fully unit-testable."""
import pandas as pd
from ..schemas.endpoints import check, ADVANCED_PLAYER, ADVANCED_TEAM


def _s(x):
    """NBA id -> clean string (never float, never loses leading zeros)."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return str(x)


def _d(x):
    return pd.to_datetime(x.astype(str).str[:10]).dt.date


def _num(df, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def is_home_from_matchup(m):
    return True if ' vs. ' in m else (False if ' @ ' in m else None)


BOX = ['MIN', 'FGM', 'FGA', 'FG3M', 'FG3A', 'FTM', 'FTA', 'OREB', 'DREB', 'REB', 'AST', 'STL', 'BLK', 'TOV', 'PF', 'PTS', 'PLUS_MINUS']


def player_game(df, season_type):
    check('LeagueGameLog', df.columns)
    d = pd.DataFrame({'game_id': df.GAME_ID.map(_s), 'player_id': df.PLAYER_ID.map(_s), 'team_id': df.TEAM_ID.map(_s),
                      'game_date': _d(df.GAME_DATE), 'season': df.SEASON_ID.astype(str).str[1:].map(season_label),
                      'season_type': season_type, 'matchup': df.MATCHUP, 'wl': df.WL, 'player_name': df.PLAYER_NAME})
    d['is_home'] = df.MATCHUP.map(is_home_from_matchup)
    num = _num(df.copy(), BOX)
    for c in BOX:
        d[c.lower()] = num[c]
    return d


def team_game(df, season_type):
    check('LeagueGameLog', df.columns)
    d = pd.DataFrame({'game_id': df.GAME_ID.map(_s), 'team_id': df.TEAM_ID.map(_s), 'game_date': _d(df.GAME_DATE),
                      'season': df.SEASON_ID.astype(str).str[1:].map(season_label), 'season_type': season_type, 'matchup': df.MATCHUP,
                      'wl': df.WL, 'team_abbreviation': df.TEAM_ABBREVIATION, 'team_name': df.TEAM_NAME})
    d['is_home'] = df.MATCHUP.map(is_home_from_matchup)
    num = _num(df.copy(), BOX)
    for c in BOX:
        d[c.lower()] = num[c]
    return d


def season_label(start_year):
    y = int(start_year)
    return f'{y}-{str(y + 1)[2:]}'


def player_extras(df):
    check('PlayerGameLogs', df.columns)
    d = pd.DataFrame({'game_id': df.GAME_ID.map(_s), 'player_id': df.PLAYER_ID.map(_s)})
    d['min_sec'] = df.get('MIN_SEC')
    d['pfd'] = pd.to_numeric(df.get('PFD'), errors='coerce')
    d['blka'] = pd.to_numeric(df.get('BLKA'), errors='coerce')
    d['_min_pgl'] = pd.to_numeric(df['MIN'], errors='coerce')
    return d


def player_advanced(df):
    check('PlayerGameLogs', df.columns, {'PLAYER_ID', 'GAME_ID', 'TEAM_ID'} | ADVANCED_PLAYER)
    g = lambda c: pd.to_numeric(df[c], errors='coerce') if c in df else pd.Series([None] * len(df), dtype='float64')
    return pd.DataFrame({'game_id': df.GAME_ID.map(_s), 'player_id': df.PLAYER_ID.map(_s), 'team_id': df.TEAM_ID.map(_s), 'min': g('MIN'),
                         'poss': g('POSS'), 'pace': g('PACE'), 'e_pace': g('E_PACE'), 'usg_pct': g('USG_PCT'), 'e_usg_pct': g('E_USG_PCT'),
                         'ts_pct': g('TS_PCT'), 'efg_pct': g('EFG_PCT'), 'ast_pct': g('AST_PCT'), 'reb_pct': g('REB_PCT'),
                         'oreb_pct': g('OREB_PCT'), 'dreb_pct': g('DREB_PCT'), 'tm_tov_pct': g('TM_TOV_PCT'), 'pie': g('PIE'),
                         'off_rating': g('OFF_RATING'), 'def_rating': g('DEF_RATING'), 'net_rating': g('NET_RATING')})


def team_advanced(df):
    check('TeamGameLogs', df.columns, {'TEAM_ID', 'GAME_ID'} | ADVANCED_TEAM)
    g = lambda c: pd.to_numeric(df[c], errors='coerce') if c in df else pd.Series([None] * len(df), dtype='float64')
    return pd.DataFrame({'game_id': df.GAME_ID.map(_s), 'team_id': df.TEAM_ID.map(_s), 'min': g('MIN'), 'poss': g('POSS'), 'pace': g('PACE'),
                         'e_pace': g('E_PACE'), 'off_rating': g('OFF_RATING'), 'def_rating': g('DEF_RATING'), 'net_rating': g('NET_RATING'),
                         'efg_pct': g('EFG_PCT'), 'ts_pct': g('TS_PCT'), 'tm_tov_pct': g('TM_TOV_PCT'), 'oreb_pct': g('OREB_PCT'),
                         'dreb_pct': g('DREB_PCT'), 'reb_pct': g('REB_PCT'), 'ast_pct': g('AST_PCT'), 'pie': g('PIE')})


def schedule(df, fetched_at):
    check('ScheduleLeagueV2', df.columns)
    tip = pd.to_datetime(df.gameDateTimeUTC, utc=True, errors='coerce').dt.tz_convert(None)
    prefix = df.gameId.astype(str).str[:3]
    return pd.DataFrame({'game_id': df.gameId.map(_s), 'id_prefix': prefix, 'game_date': _d(df.gameDateEst), 'tip_utc': tip,
                         'home_team_id': df.homeTeam_teamId.map(_s), 'away_team_id': df.awayTeam_teamId.map(_s),
                         'game_status': pd.to_numeric(df.gameStatus, errors='coerce'), 'game_label': df.get('gameLabel'),
                         'game_sub_label': df.get('gameSubLabel'), 'game_subtype': df.get('gameSubtype'), 'arena': df.get('arenaName'),
                         'is_neutral': df['isNeutral'].astype(str).str.lower().eq('true') if 'isNeutral' in df else None,
                         'schedule_fetched_at': pd.to_datetime(fetched_at).tz_localize(None) if pd.to_datetime(fetched_at).tzinfo else pd.to_datetime(fetched_at)})


def starters(df, fetched_at):
    check('BoxScoreTraditionalV3', df.columns)
    pos = df.position.fillna('').astype(str).str.strip()
    return pd.DataFrame({'game_id': df.gameId.map(_s), 'player_id': df.personId.map(_s), 'team_id': df.teamId.map(_s), 'started': pos != '',
                         'position': pos.where(pos != '', None), 'comment': df.comment.where(df.comment.notna(), None),
                         'minutes_str': df.minutes.where(df.minutes.notna(), None), 'fetched_at': pd.to_datetime(fetched_at).tz_localize(None) if pd.to_datetime(fetched_at).tzinfo else pd.to_datetime(fetched_at)})


def inactives(df, fetched_at):
    check('BoxScoreSummaryV3', df.columns)
    return pd.DataFrame({'game_id': df.gameId.map(_s), 'team_id': df.teamId.map(_s), 'player_id': df.personId.map(_s),
                         'first_name': df.get('firstName'), 'family_name': df.get('familyName'),
                         'fetched_at': pd.to_datetime(fetched_at).tz_localize(None) if pd.to_datetime(fetched_at).tzinfo else pd.to_datetime(fetched_at)})
