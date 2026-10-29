"""Chronological training-data guard. Training on results that are not yet known at the test cutoff is the most common backtest leak."""
import pandas as pd


class ChronologyError(ValueError):
    pass


def assert_chronological(train, test, label_available_col='label_available_at', cutoff_col='cutoff_ts'):
    """Every training label must have been knowable before the EARLIEST test prediction cutoff.
    train: DataFrame with the time each training label became available (e.g. available_at of its target game).
    test:  DataFrame with each test example's prediction cutoff. Raises ChronologyError with the offending rows."""
    limit = pd.to_datetime(test[cutoff_col]).min()
    late = train[pd.to_datetime(train[label_available_col]) > limit]
    if len(late):
        raise ChronologyError(f'{len(late)} training labels become available after the earliest test cutoff {limit}; first: {late.iloc[0].to_dict()}')
    return True


def purged_walk_forward(examples, n_splits, label_available_col='label_available_at', cutoff_col='cutoff_ts'):
    """Yield (train_idx, test_idx) with test blocks in time order and training restricted to labels available before each test block's cutoff."""
    ex = examples.sort_values(cutoff_col).reset_index()
    edges = [int(len(ex) * i / (n_splits + 1)) for i in range(1, n_splits + 2)]
    for a, b in zip(edges[:-1], edges[1:]):
        test = ex.iloc[a:b]
        train = ex[(pd.to_datetime(ex[label_available_col]) <= pd.to_datetime(test[cutoff_col]).min())]
        assert_chronological(train, test, label_available_col, cutoff_col)
        yield train['index'].to_numpy(), test['index'].to_numpy()
