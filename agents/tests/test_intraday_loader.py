"""
Prerequisite #3 — intraday data ingestion.

``load_intraday`` is the sub-daily counterpart to the daily ``load_data``: it
reads per-ticker intraday CSVs into the same ``ticker -> DataFrame`` shape the
Bar Engine consumes, but with a full **timestamp** (date + time) index instead of
a bare calendar date. Genuine event bars need this — on daily data an event bar
can never close within a day.

These tests prove the loader parses several timestamp layouts, yields a sorted
sub-daily DatetimeIndex, preserves OHLCV, and degrades gracefully on
empty/malformed/missing-column files (same contract as the daily loader).
"""

from __future__ import annotations

import pandas as pd
import pytest

from agents.experiment_runner.intraday_loader import (
    load_intraday,
    INTRADAY_INDEX_NAME,
)


# ---------------------------------------------------------------------------
# Fixtures — write intraday CSVs in a few common layouts
# ---------------------------------------------------------------------------

def _write_timestamp_csv(path, n=12, freq="30min", col="Timestamp") -> None:
    ts = pd.date_range("2021-06-01 09:30", periods=n, freq=freq)
    df = pd.DataFrame({
        col:      ts.strftime("%Y-%m-%d %H:%M:%S"),
        "Open":   100.0, "High": 101.0, "Low": 99.0, "Close": 100.5,
        "Volume": 1000,
    })
    df.to_csv(path, index=False)


def _write_date_time_pair_csv(path, n=12) -> None:
    ts = pd.date_range("2021-06-01 09:30", periods=n, freq="30min")
    df = pd.DataFrame({
        "Date":   ts.strftime("%Y-%m-%d"),
        "Time":   ts.strftime("%H:%M:%S"),
        "Open":   100.0, "High": 101.0, "Low": 99.0, "Close": 100.5,
        "Volume": 1000,
    })
    df.to_csv(path, index=False)


@pytest.fixture
def intraday_dir(tmp_path):
    d = tmp_path / "intraday"
    d.mkdir()
    _write_timestamp_csv(d / "aapl_us_d.csv")
    _write_timestamp_csv(d / "msft.csv")
    return d


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_loads_all_tickers(intraday_dir):
    bundle = load_intraday(intraday_dir)
    assert set(bundle.tickers_loaded) == {"AAPL", "MSFT"}


def test_index_is_sub_daily_datetimeindex(intraday_dir):
    bundle = load_intraday(intraday_dir)
    df = bundle.data_dict["AAPL"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.name == INTRADAY_INDEX_NAME
    # Multiple distinct timestamps fall on the SAME calendar date → genuinely intraday
    same_day = df.index.normalize().nunique()
    assert same_day < len(df.index)


def test_index_is_sorted(intraday_dir):
    bundle = load_intraday(intraday_dir)
    for df in bundle.data_dict.values():
        assert df.index.is_monotonic_increasing


def test_ohlcv_and_ticker_preserved(intraday_dir):
    bundle = load_intraday(intraday_dir)
    df = bundle.data_dict["AAPL"]
    for col in ("Open", "High", "Low", "Close", "Volume"):
        assert col in df.columns
    assert (df["ticker"] == "AAPL").all()
    # The timestamp source column is consumed, not left dangling as data.
    assert "Timestamp" not in df.columns


def test_no_warnings_on_clean_load(intraday_dir):
    assert load_intraday(intraday_dir).warnings == []


def test_row_count_matches_csv(intraday_dir):
    bundle = load_intraday(intraday_dir)
    assert len(bundle.data_dict["AAPL"]) == 12


# ---------------------------------------------------------------------------
# Alternative timestamp layouts
# ---------------------------------------------------------------------------

def test_date_time_pair_columns(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_date_time_pair_csv(d / "spy.csv")
    bundle = load_intraday(d)
    df = bundle.data_dict["SPY"]
    assert df.index.name == INTRADAY_INDEX_NAME
    assert df.index[0] == pd.Timestamp("2021-06-01 09:30:00")
    assert df.index[1] == pd.Timestamp("2021-06-01 10:00:00")
    assert "Date" not in df.columns and "Time" not in df.columns


def test_datetime_column_alias(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_timestamp_csv(d / "qqq.csv", col="Datetime")
    bundle = load_intraday(d)
    assert "QQQ" in bundle.data_dict
    assert bundle.data_dict["QQQ"].index[0] == pd.Timestamp("2021-06-01 09:30:00")


def test_unsorted_input_is_sorted(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    ts = ["2021-06-01 10:00:00", "2021-06-01 09:30:00", "2021-06-01 09:45:00"]
    pd.DataFrame({
        "Timestamp": ts,
        "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1,
    }).to_csv(d / "x.csv", index=False)
    df = load_intraday(d).data_dict["X"]
    assert list(df.index) == [
        pd.Timestamp("2021-06-01 09:30:00"),
        pd.Timestamp("2021-06-01 09:45:00"),
        pd.Timestamp("2021-06-01 10:00:00"),
    ]


# ---------------------------------------------------------------------------
# Error handling — same graceful-degradation contract as the daily loader
# ---------------------------------------------------------------------------

def test_missing_directory_returns_warning(tmp_path):
    bundle = load_intraday(tmp_path / "nope")
    assert bundle.data_dict == {}
    assert bundle.warnings


def test_empty_directory_returns_warning(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    bundle = load_intraday(d)
    assert bundle.data_dict == {}
    assert bundle.warnings


def test_missing_close_skipped(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_timestamp_csv(d / "good.csv")
    pd.DataFrame({"Timestamp": ["2021-06-01 09:30:00"], "Open": [1.0]}).to_csv(
        d / "bad.csv", index=False
    )
    bundle = load_intraday(d)
    assert "GOOD" in bundle.data_dict
    assert "BAD" not in bundle.data_dict
    assert any("Close" in w for w in bundle.warnings)


def test_no_timestamp_column_skipped(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_timestamp_csv(d / "good.csv")
    pd.DataFrame({
        "Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1],
    }).to_csv(d / "notime.csv", index=False)
    bundle = load_intraday(d)
    assert "GOOD" in bundle.data_dict
    assert "NOTIME" not in bundle.data_dict
    assert any("timestamp" in w.lower() for w in bundle.warnings)


def test_partial_load_continues_on_error(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_timestamp_csv(d / "good.csv")
    (d / "broken.csv").write_text("not,valid\n!!!,")
    bundle = load_intraday(d)
    assert "GOOD" in bundle.data_dict
    assert bundle.warnings


def test_deterministic_repeated_load(intraday_dir):
    a = load_intraday(intraday_dir).data_dict
    b = load_intraday(intraday_dir).data_dict
    assert set(a) == set(b)
    for t in a:
        pd.testing.assert_frame_equal(a[t], b[t])
