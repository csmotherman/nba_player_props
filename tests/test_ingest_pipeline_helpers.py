from nba_props.storage.db import connect
from nba_props.ingestion.runner import Ingestor
from nba_props.api.client import NBAClient
from tests.conftest import make_factory


def mk_ing(raw_fx, tmp_path, fail_endpoints=()):
    def fail(e, p):
        if e in fail_endpoints:
            raise TimeoutError('down')
    con = connect(':memory:')
    client = NBAClient(raw_dir=tmp_path, factory=make_factory(raw_fx, None, fail), pacing_s=0.0, max_workers=1, backoff_s=0.0, sleep=lambda s: None, max_retries=2)
    return con, Ingestor(con, client, command='test')
