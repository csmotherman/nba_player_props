"""Point-in-time (as-of) feature tables. No model, no labels.

Leak-proofing rules enforced here (and tested):
  * history row usable only if available_at(history) <= prediction_cutoff(target)   (see cutoffs.py)
  * the target game is excluded by game_id, in addition to the time rule
  * the pregame roster (`asof_roster_eligibility`) is built ONLY from appearances available at the cutoff; it never looks forward
  * the retrospective INFERRED_ABSENT appearances (derive.py) are never read by this module
  * labels live in a separate view (`v_training_examples`, prefix label_) and are never joined into feature columns
Every row records the maximum source timestamp it used and re-checks it against its own cutoff.
"""
import logging
from .. import config
from . import cutoffs
from .catalog import PLAYER_STATS, WINDOWS

log = logging.getLogger('nba_props.features')
EWMA_HALF_LIFE_GAMES = 6.0      # tunable, NOT estimated; recorded in the output for provenance
MIN_HISTORY_DAYS = 3650         # effectively unbounded: 'last N games played' must not depend on an arbitrary age cap. Staleness is exposed via window_span_days_*
ROSTER_MAX_TEAM_GAMES_SINCE = 10  # pregame eligibility: last appearance for this team within N team games (ASSUMPTION, tunable)


def prior_season(season):
    y = int(season[:4]) - 1
    return f'{y}-{str(y + 1)[2:]}'


def _fresh(con, table, select_sql, params, season, hours):
    """Idempotent per (season, cutoff): replace that slice, create the table on first use."""
    exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0]
    if exists:                       # derived data: if the feature definition changed, rebuild the table (other seasons must be rebuilt too)
        have = [r[0] for r in con.execute(f'DESCRIBE {table}').fetchall()]
        probe = con.execute(f'SELECT * FROM ({select_sql}) LIMIT 0', params).description
        want = [d[0] for d in probe]
        if have != want:
            log.warning('%s schema changed; dropping derived table (rebuild other seasons)', table)
            con.execute(f'DROP TABLE {table}')
            exists = 0
    if not exists:
        con.execute(f'CREATE TABLE {table} AS {select_sql}', params)
    else:
        con.execute(f'DELETE FROM {table} WHERE season = ? AND cutoff_hours = ?', [season, hours])
        con.execute(f'INSERT INTO {table} {select_sql}', params)
    return con.execute(f'SELECT count(*) FROM {table} WHERE season = ? AND cutoff_hours = ?', [season, hours]).fetchone()[0]


def _prepare(con):
    con.execute(f"CREATE OR REPLACE TEMP VIEW game_avail AS SELECT game_id, game_date, tip_utc, {cutoffs.sql_available_at()} AS available_at FROM games")
    con.execute(f"""CREATE OR REPLACE TEMP VIEW rest_v AS
        WITH s AS (SELECT game_id, home_team_id team_id, season, game_date FROM games WHERE season_type = 'regular' AND home_team_id IS NOT NULL
                   UNION ALL SELECT game_id, away_team_id, season, game_date FROM games WHERE season_type = 'regular' AND away_team_id IS NOT NULL)
        SELECT game_id, team_id, date_diff('day', lag(game_date) OVER (PARTITION BY team_id, season ORDER BY game_date, game_id), game_date) - 1 AS rest_days FROM s""")


def player_sql(hours):
    w = ',\n'.join(
        [f"count(*) FILTER (WHERE rn <= {n}) n_games_l{n}" for n in WINDOWS] +
        [f"avg(m) FILTER (WHERE rn <= {n}) min_mean_l{n}" for n in WINDOWS] +
        [f"quantile_cont(m, 0.5) FILTER (WHERE rn <= {n}) min_median_l{n}" for n in WINDOWS] +
        [f"stddev_samp(m) FILTER (WHERE rn <= {n}) min_std_l{n}" for n in WINDOWS] +
        [f"sum(m) FILTER (WHERE rn <= {n}) min_sum_l{n}" for n in WINDOWS] +
        [f"sum({s}) FILTER (WHERE rn <= {n}) / nullif(sum(m) FILTER (WHERE rn <= {n}), 0) {s}_pm_l{n}" for s in PLAYER_STATS for n in WINDOWS] +
        [f"sum(fga) FILTER (WHERE rn <= {n}) fga_sum_l{n}" for n in WINDOWS] +
        [f"sum({s}) FILTER (WHERE h_season = $prior) / nullif(sum(m) FILTER (WHERE h_season = $prior), 0) prior_{s}_pm" for s in PLAYER_STATS])
    return f"""
    WITH tgt AS (
      SELECT p.game_id, p.player_id, p.team_id, p.opp_team_id, p.is_home, p.game_date, p.season, g.tip_utc, (g.tip_utc IS NOT NULL) AS tip_known,
             {cutoffs.sql_cutoff(hours, 'g.tip_utc', 'p.game_date')} AS cutoff_ts
      FROM player_game p JOIN games g USING (game_id) WHERE p.season = $season AND p.season_type = 'regular'),
    h AS (
      SELECT t.game_id tg, t.player_id tp, t.cutoff_ts, t.game_date t_date, t.season t_season,
             x.game_id hg, x.team_id h_team, x.game_date h_date, x.season h_season, x.min_exact m, x.pts, x.reb, x.ast, x.fg3a, x.fga,
             a.available_at, s.started
      FROM tgt t
      JOIN player_game x ON x.player_id = t.player_id AND x.game_id <> t.game_id AND x.min_exact > 0 AND x.season_type = 'regular'
                        AND x.game_date >= t.game_date - INTERVAL {MIN_HISTORY_DAYS} DAY AND x.game_date <= t.game_date
      JOIN game_avail a ON a.game_id = x.game_id AND a.available_at <= t.cutoff_ts
      LEFT JOIN historical_starters s ON s.game_id = x.game_id AND s.player_id = x.player_id),
    r AS (
      SELECT *, row_number() OVER w rn, first_value(h_team) OVER w latest_team,
             CASE WHEN h_team <> lag(h_team) OVER w THEN 1 ELSE 0 END changed_vs_newer
      FROM h WINDOW w AS (PARTITION BY tg, tp ORDER BY available_at DESC, hg DESC)),
    agg AS (
      SELECT tg, tp, count(*) n_hist_games, any_value(latest_team) asof_team_id,
             coalesce(min(rn) FILTER (WHERE h_team <> latest_team) - 1, count(*)) games_with_team_asof,
             coalesce(sum(changed_vs_newer) FILTER (WHERE h_date >= t_date - INTERVAL 365 DAY), 0) team_changes_365d,
             date_diff('day', max(h_date), t_date) days_since_last_game,
             date_diff('day', min(h_date) FILTER (WHERE rn <= 10), t_date) window_span_days_l10,
             date_diff('day', min(h_date) FILTER (WHERE rn <= 20), t_date) window_span_days_l20,
             {w},
             avg(started::INT) FILTER (WHERE rn <= 10 AND started IS NOT NULL) start_rate_l10,
             count(started) FILTER (WHERE rn <= 10) start_games_covered_l10,
             count(*) FILTER (WHERE h_season = $prior) prior_season_games, sum(m) FILTER (WHERE h_season = $prior) prior_season_min,
             count(*) FILTER (WHERE h_season = t_season) std_games, sum(m) FILTER (WHERE h_season = t_season) std_min,
             sum(m * pow(0.5, (rn - 1) / {EWMA_HALF_LIFE_GAMES})) FILTER (WHERE rn <= 20) / nullif(sum(pow(0.5, (rn - 1) / {EWMA_HALF_LIFE_GAMES})) FILTER (WHERE rn <= 20), 0) min_ewma_l20,
             max(available_at) max_source_available_at, max(h_date) max_source_game_date
      FROM r GROUP BY tg, tp, t_date, t_season)
    SELECT t.game_id, t.player_id, CAST({hours} AS DOUBLE) cutoff_hours, t.season, t.game_date, t.tip_utc, t.tip_known, t.cutoff_ts,
           t.team_id, t.opp_team_id, t.is_home,
           a.asof_team_id, (a.asof_team_id IS NOT NULL AND a.asof_team_id <> t.team_id) team_changed_vs_last,
           coalesce(a.n_hist_games, 0) n_hist_games, a.games_with_team_asof, coalesce(a.team_changes_365d, 0) team_changes_365d, a.days_since_last_game,
           a.* EXCLUDE (tg, tp, n_hist_games, asof_team_id, games_with_team_asof, team_changes_365d, days_since_last_game, max_source_available_at, max_source_game_date),
           coalesce(a.n_games_l5, 0) < 5 low_sample_l5, coalesce(a.n_games_l10, 0) < 10 low_sample_l10, coalesce(a.n_games_l20, 0) < 20 low_sample_l20,
           coalesce(a.prior_season_games, 0) = 0 no_prior_season, coalesce(a.n_hist_games, 0) = 0 no_history_in_warehouse,
           a.min_ewma_l20 IS NULL missing_min_ewma, a.start_games_covered_l10 IS NULL OR a.start_games_covered_l10 = 0 missing_starter_info,
           a.max_source_available_at, a.max_source_game_date,
           coalesce(a.max_source_available_at <= t.cutoff_ts, TRUE) inputs_available_at_cutoff,
           CAST({EWMA_HALF_LIFE_GAMES} AS DOUBLE) ewma_half_life_games, CAST({config.COMPLETION_BUFFER_H} AS DOUBLE) completion_buffer_h,
           CASE WHEN t.tip_known THEN 'tip-based cutoff; completion time ASSUMED = tip + buffer' ELSE 'tip unknown: conservative date-based cutoff/availability' END limitations
    FROM tgt t LEFT JOIN agg a ON a.tg = t.game_id AND a.tp = t.player_id"""


def team_sql(hours):
    return f"""
    WITH tt AS (
      SELECT t.game_id, t.team_id, t.opp_team_id, t.is_home, t.game_date, t.season, g.tip_utc, (g.tip_utc IS NOT NULL) tip_known,
             {cutoffs.sql_cutoff(hours, 'g.tip_utc', 't.game_date')} cutoff_ts
      FROM team_game t JOIN games g USING (game_id) WHERE t.season = $season AND t.season_type = 'regular'),
    th AS (
      SELECT t.game_id tg, t.team_id tt_, x.game_id hg, ta.poss, ta.min amin, ta.off_rating, ta.def_rating, a.available_at, x.game_date h_date
      FROM tt t JOIN team_game x ON x.team_id = t.team_id AND x.game_id <> t.game_id AND x.season_type = 'regular'
                                AND x.game_date >= t.game_date - INTERVAL 400 DAY AND x.game_date <= t.game_date
      JOIN team_advanced_game ta ON ta.game_id = x.game_id AND ta.team_id = x.team_id
      JOIN game_avail a ON a.game_id = x.game_id AND a.available_at <= t.cutoff_ts),
    r AS (SELECT *, row_number() OVER (PARTITION BY tg, tt_ ORDER BY available_at DESC, hg DESC) rn FROM th),
    env AS (
      SELECT tg game_id, tt_ team_id, count(*) n_hist_games,
             count(*) FILTER (WHERE rn <= 5) n_games_l5, count(*) FILTER (WHERE rn <= 10) n_games_l10,
             avg(poss) FILTER (WHERE rn <= 5) poss_l5, avg(poss) FILTER (WHERE rn <= 10) poss_l10,
             48 * sum(poss) FILTER (WHERE rn <= 5) / nullif(sum(amin) FILTER (WHERE rn <= 5), 0) pace_l5,
             48 * sum(poss) FILTER (WHERE rn <= 10) / nullif(sum(amin) FILTER (WHERE rn <= 10), 0) pace_l10,
             sum(off_rating * poss) FILTER (WHERE rn <= 10) / nullif(sum(poss) FILTER (WHERE rn <= 10), 0) off_rating_l10,
             sum(def_rating * poss) FILTER (WHERE rn <= 10) / nullif(sum(poss) FILTER (WHERE rn <= 10), 0) def_rating_l10,
             max(available_at) max_source_available_at, max(h_date) max_source_game_date
      FROM r GROUP BY tg, tt_),
    base AS (
      SELECT t.*, e.n_hist_games, e.n_games_l5, e.n_games_l10, e.poss_l5, e.poss_l10, e.pace_l5, e.pace_l10, e.off_rating_l10, e.def_rating_l10,
             e.max_source_available_at, e.max_source_game_date, rv.rest_days
      FROM tt t LEFT JOIN env e ON e.game_id = t.game_id AND e.team_id = t.team_id
                LEFT JOIN rest_v rv ON rv.game_id = t.game_id AND rv.team_id = t.team_id)
    SELECT b.game_id, b.team_id, CAST({hours} AS DOUBLE) cutoff_hours, b.season, b.game_date, b.tip_utc, b.tip_known, b.cutoff_ts, b.opp_team_id, b.is_home,
           coalesce(b.n_hist_games, 0) n_hist_games, coalesce(b.n_games_l5, 0) n_games_l5, coalesce(b.n_games_l10, 0) n_games_l10,
           b.poss_l5, b.poss_l10, b.pace_l5, b.pace_l10, b.off_rating_l10, b.def_rating_l10,
           o.poss_l10 opp_poss_l10, o.pace_l10 opp_pace_l10, o.off_rating_l10 opp_off_rating_l10, o.def_rating_l10 opp_def_rating_l10,
           b.rest_days, b.rest_days = 0 is_back_to_back, o.rest_days opp_rest_days, o.rest_days = 0 opp_is_back_to_back,
           coalesce(b.n_games_l10, 0) < 10 low_sample_l10, b.rest_days IS NULL missing_rest_days,
           greatest(b.max_source_available_at, o.max_source_available_at) max_source_available_at,
           greatest(b.max_source_game_date, o.max_source_game_date) max_source_game_date,
           coalesce(greatest(b.max_source_available_at, o.max_source_available_at) <= b.cutoff_ts, TRUE) inputs_available_at_cutoff
    FROM base b LEFT JOIN base o ON o.game_id = b.game_id AND o.team_id = b.opp_team_id"""


def roster_sql(hours):
    return f"""
    WITH tt AS (
      SELECT t.game_id, t.team_id, t.game_date, t.season, {cutoffs.sql_cutoff(hours, 'g.tip_utc', 't.game_date')} cutoff_ts
      FROM team_game t JOIN games g USING (game_id) WHERE t.season = $season AND t.season_type = 'regular'),
    cand AS (
      SELECT DISTINCT t.game_id, t.team_id, x.player_id, t.game_date, t.cutoff_ts
      FROM tt t JOIN player_game x ON x.team_id = t.team_id AND x.min_exact > 0 AND x.season_type = 'regular'
                                  AND x.game_date < t.game_date AND x.game_date >= t.game_date - INTERVAL 120 DAY
      JOIN game_avail a ON a.game_id = x.game_id AND a.available_at <= t.cutoff_ts),
    last_app AS (
      SELECT c.game_id, c.team_id, c.player_id, c.game_date, arg_max(y.team_id, a.available_at) last_team, max(y.game_date) last_date
      FROM cand c JOIN player_game y ON y.player_id = c.player_id AND y.min_exact > 0 AND y.season_type = 'regular' AND y.game_date < c.game_date
      JOIN game_avail a ON a.game_id = y.game_id AND a.available_at <= c.cutoff_ts
      GROUP BY c.game_id, c.team_id, c.player_id, c.game_date)
    SELECT l.game_id, l.team_id, l.player_id, CAST({hours} AS DOUBLE) cutoff_hours, CAST($season AS VARCHAR) season, l.last_date, l.last_team,
           (SELECT count(*) FROM games gg WHERE gg.season_type = 'regular' AND l.team_id IN (gg.home_team_id, gg.away_team_id)
              AND gg.game_date > l.last_date AND gg.game_date < l.game_date) team_games_since_last,
           l.last_team = l.team_id AND (SELECT count(*) FROM games gg WHERE gg.season_type = 'regular' AND l.team_id IN (gg.home_team_id, gg.away_team_id)
              AND gg.game_date > l.last_date AND gg.game_date < l.game_date) <= {ROSTER_MAX_TEAM_GAMES_SINCE} eligible,
           EXISTS (SELECT 1 FROM player_game p WHERE p.game_id = l.game_id AND p.player_id = l.player_id AND p.min_exact > 0) label_actually_played
    FROM last_app l"""


def build(con, season, hours_list=config.DEFAULT_CUTOFF_HOURS):
    _prepare(con)
    out = {}
    for h in hours_list:
        h = float(h)
        out[f'player@{h:g}h'] = _fresh(con, 'asof_player_features', player_sql(h), {'season': season, 'prior': prior_season(season)}, season, h)
        out[f'team@{h:g}h'] = _fresh(con, 'asof_team_features', team_sql(h), {'season': season}, season, h)
        out[f'roster@{h:g}h'] = _fresh(con, 'asof_roster_eligibility', roster_sql(h), {'season': season}, season, h)
    con.execute("""CREATE OR REPLACE VIEW v_training_examples AS
        SELECT f.*, tf.pace_l10 team_pace_l10, tf.off_rating_l10 team_off_rating_l10, tf.def_rating_l10 team_def_rating_l10, tf.poss_l10 team_poss_l10,
               tf.pace_l5 team_pace_l5, tf.poss_l5 team_poss_l5, tf.opp_pace_l10, tf.opp_poss_l10, tf.opp_off_rating_l10, tf.opp_def_rating_l10,
               tf.rest_days, tf.is_back_to_back, tf.opp_rest_days, tf.opp_is_back_to_back,
               p.min_exact label_min, p.pts label_pts, p.reb label_reb, p.ast label_ast, p.fg3a label_fg3a, p.fga label_fga
        FROM asof_player_features f
        JOIN asof_team_features tf ON tf.game_id = f.game_id AND tf.team_id = f.team_id AND tf.cutoff_hours = f.cutoff_hours
        JOIN player_game p ON p.game_id = f.game_id AND p.player_id = f.player_id""")
    return out


def explain(con, game_id, player_id, hours):
    """Why was each input available at the cutoff? Returns the cutoff and every history row used (for audit)."""
    row = con.execute("SELECT cutoff_ts, max_source_available_at, max_source_game_date, inputs_available_at_cutoff, limitations FROM asof_player_features "
                      "WHERE game_id = ? AND player_id = ? AND cutoff_hours = ?", [game_id, player_id, float(hours)]).fetchone()
    used = con.execute(f"""SELECT x.game_id, x.game_date, a.available_at, a.available_at <= ? AS available_at_cutoff FROM player_game x JOIN game_avail a USING (game_id)
                           WHERE x.player_id = ? AND x.game_id <> ? AND x.min_exact > 0 AND x.season_type = 'regular' AND a.available_at <= ?
                           ORDER BY a.available_at DESC LIMIT 20""", [row[0], player_id, game_id, row[0]]).fetchall()
    return dict(cutoff_ts=row[0], max_source_available_at=row[1], max_source_game_date=row[2], inputs_available_at_cutoff=row[3], limitations=row[4],
                last20_sources=[dict(game_id=u[0], game_date=u[1], available_at=u[2], ok=u[3]) for u in used])
