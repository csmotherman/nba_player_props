"""Time semantics for point-in-time features. Pure helpers; the SQL below must agree with them (unit-tested).

Four distinct times are never conflated:
  event_time        when the game happened (tip_utc; completion is NOT exposed by the endpoints used)
  published_at      when a fact became publicly known. Unknown for historical box scores => modelled by `available_at`
  fetched_at        when WE downloaded it (source_requests); says nothing about when it was knowable
  prediction_cutoff the moment a prediction is made: tip_utc - H hours (or the conservative fallback below)

available_at(game) = tip_utc + COMPLETION_BUFFER_H                        if tip is known
                   = (game_date + 1 day) + 12h  (UTC)                      if tip is unknown   (conservative: after any US evening game)
cutoff_ts(game, H) = tip_utc - H hours                                     if tip is known
                   = game_date 00:00 UTC - H hours                         if tip is unknown   (conservative: before any NBA tip on that date)
A history row is usable for a target iff available_at(history) <= cutoff_ts(target) AND it is a different game.
"""
from datetime import datetime, timedelta, date
from .. import config


def available_at(tip_utc, game_date, buffer_h=None):
    buffer_h = config.COMPLETION_BUFFER_H if buffer_h is None else buffer_h
    if tip_utc is not None:
        return tip_utc + timedelta(hours=buffer_h)
    d = game_date if isinstance(game_date, date) else game_date.date()
    return datetime(d.year, d.month, d.day) + timedelta(days=1, hours=12)


def cutoff_ts(tip_utc, game_date, hours):
    if tip_utc is not None:
        return tip_utc - timedelta(hours=hours)
    d = game_date if isinstance(game_date, date) else game_date.date()
    return datetime(d.year, d.month, d.day) - timedelta(hours=hours)


def sql_available_at(buffer_h=None, tip='tip_utc', gd='game_date'):
    b = config.COMPLETION_BUFFER_H if buffer_h is None else buffer_h
    return f"COALESCE({tip} + INTERVAL ({b}) HOUR, CAST({gd} AS TIMESTAMP) + INTERVAL 1 DAY + INTERVAL 12 HOUR)"


def sql_cutoff(hours, tip='tip_utc', gd='game_date'):
    return f"COALESCE({tip}, CAST({gd} AS TIMESTAMP)) - INTERVAL ({hours}) HOUR"
