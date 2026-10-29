"""Paths and tunable constants. Everything that is an *assumption* is named and documented here."""
import os
from pathlib import Path

ROOT = Path(os.environ.get('NBA_PROPS_ROOT', Path(__file__).resolve().parent.parent))
RAW_DIR = Path(os.environ.get('NBA_PROPS_RAW', ROOT / 'data' / 'raw'))
DB_PATH = Path(os.environ.get('NBA_PROPS_DB', ROOT / 'data' / 'warehouse' / 'nba.duckdb'))
PROCESSED_DIR = ROOT / 'data' / 'processed'

# Season types requested from the API. Classification is VERIFIED against game-id prefix and schedule labels (validation.quality).
SEASON_TYPES = {'Regular Season': 'regular', 'Playoffs': 'playoffs', 'PlayIn': 'playin', 'Pre Season': 'preseason'}
DEFAULT_SEASON_TYPES = ('Regular Season',)
ID_PREFIX_TYPE = {'001': 'preseason', '002': 'regular', '003': 'allstar', '004': 'playoffs', '005': 'playin', '006': 'cup_final'}

# Client defaults: deliberately conservative. The API is unofficial.
PACING_S = 1.5           # minimum seconds between request starts (global, across threads). 0.7s/2 workers got the IP throttled after ~900 requests
MAX_WORKERS = 1          # bounded concurrency
BREAKER_THRESHOLD = 3        # consecutive failures that trip the global circuit breaker
BREAKER_COOLDOWN_S = 60.0
BREAKER_MAX_COOLDOWN_S = 600.0
TIMEOUT_S = 45
MAX_RETRIES = 4
BACKOFF_S = 2.0

# ASSUMPTION (flagged in every report): completion time of a game is not exposed by the endpoints used.
# A game is treated as "available" (final box score knowable) COMPLETION_BUFFER_H hours after tip-off.
# NBA games rarely exceed ~3.5h even with overtime; 4h is conservative. Override to test sensitivity.
COMPLETION_BUFFER_H = 4.0
# If tip-off time is unknown, a game is available from the START of the next calendar day (UTC) after its date.
DEFAULT_CUTOFF_HOURS = (24, 6, 1)
