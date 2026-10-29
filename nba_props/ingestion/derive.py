"""Derived warehouse tables (pure SQL on already-loaded data): games backfill, teams, players, stints, appearances."""
DERIVE_SQL = [
    # LeagueGameLog MIN is rounded to whole minutes (100% integer, verified). MIN_SEC (PlayerGameLogs) has seconds.
    # Use it only when it agrees with MIN within 1 minute; otherwise keep MIN and flag a cross-source conflict.
    """UPDATE player_game SET
         min_conflict = (min_sec LIKE '%:%' AND abs(min - (CAST(split_part(min_sec,':',1) AS DOUBLE) + CAST(split_part(min_sec,':',2) AS DOUBLE)/60)) > 1.0),
         min_exact = CASE WHEN min_sec LIKE '%:%' AND abs(min - (CAST(split_part(min_sec,':',1) AS DOUBLE) + CAST(split_part(min_sec,':',2) AS DOUBLE)/60)) <= 1.0
                          THEN CAST(split_part(min_sec,':',1) AS DOUBLE) + CAST(split_part(min_sec,':',2) AS DOUBLE)/60 ELSE min END""",
    # games known from box scores but absent from the schedule listing
    """INSERT INTO games(game_id, season, season_type, season_type_source, id_prefix, game_date, home_team_id, away_team_id, in_schedule, in_gamelog)
       SELECT t.game_id, any_value(t.season), any_value(t.season_type), 'gamelog_request', substr(t.game_id,1,3), any_value(t.game_date),
              max(CASE WHEN t.is_home THEN t.team_id END), max(CASE WHEN NOT t.is_home THEN t.team_id END), FALSE, TRUE
       FROM team_game t WHERE t.game_id NOT IN (SELECT game_id FROM games) GROUP BY t.game_id""",
    """UPDATE games SET in_gamelog = TRUE WHERE game_id IN (SELECT game_id FROM team_game)""",
    """UPDATE games g SET season = t.season, season_type = t.season_type, season_type_source = 'gamelog_request',
              home_score = t.hs, away_score = t.as_
       FROM (SELECT game_id, any_value(season) season, any_value(season_type) season_type,
                    max(CASE WHEN is_home THEN pts END) hs, max(CASE WHEN NOT is_home THEN pts END) as_ FROM team_game GROUP BY game_id) t
       WHERE g.game_id = t.game_id""",
    # opponent ids
    """UPDATE team_game t SET opp_team_id = CASE WHEN t.team_id = g.home_team_id THEN g.away_team_id ELSE g.home_team_id END
       FROM games g WHERE g.game_id = t.game_id""",
    """UPDATE player_game p SET opp_team_id = CASE WHEN p.team_id = g.home_team_id THEN g.away_team_id ELSE g.home_team_id END
       FROM games g WHERE g.game_id = p.game_id""",
    # MATCHUP-derived is_home is wrong for neutral-site games (both teams read '@'): the schedule designation is authoritative
    """UPDATE team_game t SET is_home = (t.team_id = g.home_team_id) FROM games g WHERE g.game_id = t.game_id AND g.home_team_id IS NOT NULL AND g.home_team_id <> '0'""",
    """UPDATE player_game p SET is_home = (p.team_id = g.home_team_id) FROM games g WHERE g.game_id = p.game_id AND g.home_team_id IS NOT NULL AND g.home_team_id <> '0'""",
    """INSERT OR REPLACE INTO teams SELECT team_id, any_value(team_abbreviation), any_value(team_name), min(game_date), max(game_date) FROM team_game GROUP BY team_id""",
    """INSERT OR REPLACE INTO players SELECT player_id, arg_max(player_name, game_date), min(game_date), max(game_date), count(*) FROM player_game GROUP BY player_id""",
    # stints of consecutive games with the same team (gaps-and-islands), across seasons
    """DELETE FROM player_team_history""",
    """INSERT INTO player_team_history
       WITH o AS (SELECT player_id, team_id, game_date, game_id,
                         row_number() OVER (PARTITION BY player_id ORDER BY game_date, game_id) rn,
                         row_number() OVER (PARTITION BY player_id, team_id ORDER BY game_date, game_id) rt FROM player_game),
            s AS (SELECT player_id, team_id, rn - rt grp, min(game_date) a, max(game_date) b, count(*) n FROM o GROUP BY player_id, team_id, rn - rt)
       SELECT player_id, team_id, a, b, n, row_number() OVER (PARTITION BY player_id ORDER BY a) FROM s""",
    # appearances (confirmed from box scores)
    """DELETE FROM player_appearances""",
    """INSERT INTO player_appearances SELECT game_id, player_id, team_id, CASE WHEN min > 0 THEN 'APPEARED' ELSE 'ZERO_MIN' END,
              'confirmed', 'player_game', NULL FROM player_game""",
    """INSERT OR REPLACE INTO player_appearances SELECT game_id, player_id, team_id, 'CONFIRMED_DNP', 'confirmed', 'boxscore_v3_comment', comment
       FROM historical_starters WHERE comment IS NOT NULL AND (comment ILIKE 'DNP%' OR comment ILIKE 'DND%' OR comment ILIKE 'NWT%')""",
    """INSERT OR REPLACE INTO player_appearances SELECT game_id, player_id, team_id, 'OFFICIAL_INACTIVE', 'confirmed', 'summary_v3_inactives', NULL FROM historical_inactives""",
    # RETROSPECTIVE inference: uses games AFTER the target => never allowed to feed pregame features
    """INSERT OR REPLACE INTO player_appearances
       WITH tg AS (SELECT game_id, team_id, season, game_date FROM team_game),
            seen AS (SELECT DISTINCT player_id, team_id, season, game_date FROM player_game WHERE min > 0)
       SELECT tg.game_id, s.player_id, tg.team_id, 'INFERRED_ABSENT', 'retrospective_inference_uses_future', 'roster_window_both_sides', NULL
       FROM tg JOIN (SELECT player_id, team_id, season, min(game_date) first_d, max(game_date) last_d FROM seen GROUP BY ALL) s
         ON s.team_id = tg.team_id AND s.season = tg.season AND s.first_d < tg.game_date AND s.last_d > tg.game_date
       WHERE NOT EXISTS (SELECT 1 FROM player_game p WHERE p.game_id = tg.game_id AND p.player_id = s.player_id)""",
]


def run(con):
    for q in DERIVE_SQL:
        con.execute(q)
