"""python -m nba_props <command>   (ingest | boxscores | validate | features | report | status | tracking-pilot)"""
import argparse, logging, sys
from . import config


def _season_list(s):
    return [x.strip() for x in s.split(',') if x.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(prog='nba_props', description=__doc__)
    p.add_argument('--db', default=None, help='DuckDB path (default data/warehouse/nba.duckdb)')
    p.add_argument('-v', '--verbose', action='store_true')
    sub = p.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('ingest', help='schedule + game logs (+ advanced) for one or more seasons')
    a.add_argument('--season', required=True, type=_season_list, help='e.g. 2025-26 or 2024-25,2025-26')
    a.add_argument('--incremental', action='store_true', help='refetch (current season); otherwise completed requests are replayed from data/raw')
    a.add_argument('--season-types', default=','.join(config.DEFAULT_SEASON_TYPES), help='comma list: Regular Season,Playoffs,PlayIn,Pre Season')
    a.add_argument('--boxscores', action='store_true', help='also fetch per-game V3 box scores (starters/DNP) and summaries (inactives)')
    a.add_argument('--max-games', type=int, default=None, help='cap per-game box-score requests (pilot/resume)')
    a.add_argument('--workers', type=int, default=None); a.add_argument('--pacing', type=float, default=None)

    b = sub.add_parser('boxscores', help='only per-game V3 box scores/summaries (resumable)')
    b.add_argument('--season', required=True, type=_season_list); b.add_argument('--max-games', type=int, default=None)
    b.add_argument('--no-inactives', action='store_true'); b.add_argument('--workers', type=int, default=None); b.add_argument('--pacing', type=float, default=None)

    v = sub.add_parser('validate', help='run data-quality checks and store results')
    v.add_argument('--season', type=_season_list, default=None)

    f = sub.add_parser('features', help='build point-in-time (as-of) feature tables')
    f.add_argument('--season', required=True, type=_season_list)
    f.add_argument('--cutoff-hours', default=','.join(map(str, config.DEFAULT_CUTOFF_HOURS)))

    r = sub.add_parser('report', help='write NBA_DATA_QUALITY_REPORT.md from the warehouse')
    sub.add_parser('status', help='warehouse contents and last runs')

    t = sub.add_parser('tracking-pilot', help='OPTIONAL: date-window tracking coverage pilot (isolated)')
    t.add_argument('--dates-per-season', type=int, default=4)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    from .storage.db import connect
    con = connect(args.db)

    if args.cmd in ('ingest', 'boxscores'):
        from .api.client import NBAClient
        from .ingestion.runner import Ingestor
        client = NBAClient(max_workers=args.workers, pacing_s=args.pacing)
        ing = Ingestor(con, client, command=args.cmd, season=','.join(args.season))
        try:
            for s in args.season:
                if args.cmd == 'ingest':
                    st = [x.strip() for x in args.season_types.split(',')]
                    print(s, ing.ingest_season(s, st, refresh=args.incremental))
                    if args.boxscores:
                        ing.ingest_boxscores(s, max_games=args.max_games)
                else:
                    ing.ingest_boxscores(s, inactives=not args.no_inactives, max_games=args.max_games)
            ing.finish('ok')
        except KeyboardInterrupt:
            ing.finish('interrupted'); print('interrupted: progress is saved; rerun the same command to resume'); return 130
        except Exception as e:
            ing.finish('error', f'{type(e).__name__}: {e}'); raise
        print(f'requests={ing.n_req} failures={ing.n_fail}')
    elif args.cmd == 'validate':
        from .validation import quality
        res = quality.run_all(con, args.season)
        bad = [r for r in res if not r['passed'] and r['severity'] == 'error']
        print(f'{len(res)} checks, {len(bad)} failed (error severity)')
        for r in res:
            if not r['passed']:
                print(f"  [{r['severity']}] {r['check_name']} {r['season']}: observed={r['observed']} expected={r['expected']}")
        return 1 if bad else 0
    elif args.cmd == 'features':
        from .features import asof
        for s in args.season:
            print(s, asof.build(con, s, [float(x) for x in args.cutoff_hours.split(',')]))
    elif args.cmd == 'report':
        from .validation import report
        print(report.write(con))
    elif args.cmd == 'status':
        from .validation import quality
        print(quality.status(con))
    elif args.cmd == 'tracking-pilot':
        from .tracking import pilot
        print(pilot.run(con, args.dates_per_season))
    return 0
