"""Rate-limited, retrying NBA API client with an append-only raw-response store.

* one global pacing lock (min interval between request starts) + bounded worker pool
* retry with exponential backoff + jitter on transient failures; bad-parameter errors are not retried
* every successful response is written atomically to data/raw/<endpoint>/<sha256>.json.gz and never modified
* responses can be re-parsed offline from the raw store (replay), so ingestion is resumable without the network
"""
import gzip, hashlib, importlib, json, logging, os, random, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from .. import config

log = logging.getLogger('nba_props.api')
ENDPOINT_MODULES = {'stats': 'nba_api.stats.endpoints', 'live': 'nba_api.live.nba.endpoints'}


class TransientError(RuntimeError):
    pass


@dataclass
class FetchResult:
    endpoint: str
    params: dict
    params_hash: str
    ok: bool
    raw: dict | None = None
    sha256: str | None = None
    raw_path: str | None = None
    fetched_at: str | None = None
    duration_s: float = 0.0
    attempts: int = 0
    error: str | None = None
    from_cache: bool = False
    meta: dict = field(default_factory=dict)


def params_hash(endpoint, params):
    return hashlib.sha1(json.dumps([endpoint, params], sort_keys=True, default=str).encode()).hexdigest()[:16]


def endpoint_class(name, module='stats'):
    return getattr(importlib.import_module(ENDPOINT_MODULES[module]), name)


def parse_frames(endpoint, params, raw, module='stats'):
    """Rebuild DataFrames from a stored raw dict using nba_api's own parser (no network)."""
    from nba_api.stats.library.http import NBAStatsResponse as NBAResponse
    cls = endpoint_class(endpoint, module)
    ep = cls(**params, get_request=False)
    ep.nba_response = NBAResponse(json.dumps(raw), 200, '')
    ep.load_response()
    dfs = ep.get_data_frames()
    names = list(getattr(ep, 'expected_data', {}).keys())
    if len(names) != len(dfs):
        names = [f'set{i}' for i in range(len(dfs))]
    return dict(zip(names, dfs))


class NBAClient:
    def __init__(self, raw_dir=None, pacing_s=None, max_workers=None, timeout=None, max_retries=None, backoff_s=None,
                 sleep=time.sleep, clock=time.monotonic, factory=None):
        self.raw_dir = Path(raw_dir or config.RAW_DIR)
        self.pacing_s = config.PACING_S if pacing_s is None else pacing_s
        self.max_workers = max_workers or config.MAX_WORKERS
        self.timeout = timeout or config.TIMEOUT_S
        self.max_retries = max_retries or config.MAX_RETRIES
        self.backoff_s = config.BACKOFF_S if backoff_s is None else backoff_s
        self._sleep, self._clock = sleep, clock
        self._lock = threading.Lock()
        self._next = 0.0
        self._fails = 0                              # consecutive failures across all threads (circuit breaker)
        self._cool_until = 0.0
        self._factory = factory                      # injectable for tests: factory(endpoint, params, timeout) -> dict
        try:
            self.api_version = metadata.version('nba_api')
        except Exception:
            self.api_version = 'unknown'

    # ---- pacing -------------------------------------------------------------------------------------------
    def _pace(self):
        with self._lock:
            now = self._clock()
            wait = max(0.0, self._next - now, self._cool_until - now)       # honour a global cooldown after repeated failures
            self._next = max(now, self._next) + self.pacing_s + (wait if self._cool_until > now else 0)
        if wait:
            self._sleep(wait)

    # ---- single request -----------------------------------------------------------------------------------
    def _request(self, endpoint, params, module):
        if self._factory:
            return self._factory(endpoint, params, self.timeout)
        ep = endpoint_class(endpoint, module)(**params, timeout=self.timeout)
        raw = ep.nba_response.get_dict() if hasattr(ep, 'nba_response') else ep.get_dict()
        if not raw:
            raise TransientError('empty response body')
        return raw

    def fetch(self, endpoint, params, module='stats'):
        h = params_hash(endpoint, params)
        t0 = self._clock(); err = None
        for attempt in range(1, self.max_retries + 1):
            self._pace()
            try:
                raw = self._request(endpoint, params, module)
                sha, path = self._store(endpoint, raw)
                with self._lock:
                    self._fails = 0
                return FetchResult(endpoint, params, h, True, raw, sha, str(path), datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                   self._clock() - t0, attempt)
            except TypeError as e:                     # wrong keyword for our call: permanent
                err = f'{type(e).__name__}: {e}'; break
            except Exception as e:                      # timeouts, JSON decode, connection errors, KeyError on empty payloads
                err = f'{type(e).__name__}: {str(e)[:160]}'
                log.warning('%s %s attempt %d/%d failed: %s', endpoint, params, attempt, self.max_retries, err)
                with self._lock:
                    self._fails += 1
                    if self._fails >= config.BREAKER_THRESHOLD:       # looks like throttling: back off globally, not per request
                        cool = min(config.BREAKER_MAX_COOLDOWN_S, config.BREAKER_COOLDOWN_S * 2 ** (self._fails - config.BREAKER_THRESHOLD))
                        self._cool_until = self._clock() + cool
                        log.error('circuit breaker: %d consecutive failures, cooling down %.0fs', self._fails, cool)
                if attempt < self.max_retries:
                    self._sleep(self.backoff_s * (2 ** (attempt - 1)) * (0.75 + random.random() / 2))
        return FetchResult(endpoint, params, h, False, None, None, None, datetime.now(timezone.utc).isoformat(timespec='seconds'),
                           self._clock() - t0, attempt, err)

    def fetch_many(self, requests):
        """requests: iterable of (endpoint, params). Yields FetchResult as they complete (bounded concurrency)."""
        with ThreadPoolExecutor(self.max_workers) as ex:
            futs = [ex.submit(self.fetch, e, p) for e, p in requests]
            for f in as_completed(futs):
                yield f.result()

    # ---- raw store ----------------------------------------------------------------------------------------
    def _store(self, endpoint, raw):
        body = json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()
        sha = hashlib.sha256(body).hexdigest()
        d = self.raw_dir / endpoint
        d.mkdir(parents=True, exist_ok=True)
        path = d / f'{sha}.json.gz'
        if not path.exists():                          # content-addressed => append-only and idempotent
            fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
            with os.fdopen(fd, 'wb') as fh:
                fh.write(gzip.compress(body, 6, mtime=0))
            os.replace(tmp, path)                      # atomic
        return sha, path

    @staticmethod
    def load_raw(path):
        return json.loads(gzip.decompress(Path(path).read_bytes()))
