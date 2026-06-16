"""Tests for experiment_runner/data_loader.py."""

import pandas as pd
import pytest
from pathlib import Path

from agents.experiment_runner.data_loader import load_data, _ticker_from_path


# ---------------------------------------------------------------------------
# _ticker_from_path
# ---------------------------------------------------------------------------

def test_ticker_strips_us_d_suffix():
    assert _ticker_from_path(Path("aapl_us_d.csv")) == "AAPL"


def test_ticker_plain_uppercase():
    assert _ticker_from_path(Path("MSFT.csv")) == "MSFT"


def test_ticker_plain_lowercase():
    assert _ticker_from_path(Path("spy.csv")) == "SPY"


def test_ticker_strips_us_w_suffix():
    assert _ticker_from_path(Path("gs_us_w.csv")) == "GS"


def test_ticker_no_known_suffix_unchanged():
    assert _ticker_from_path(Path("somefund_daily.csv")) == "SOMEFUND_DAILY"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_csv(path: Path, n: int = 50) -> None:
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "Date": dates.strftime("%Y-%m-%d"),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000,
    })
    df.to_csv(path, index=False)


@pytest.fixture
def universe_dir(tmp_path):
    d = tmp_path / "universe"
    d.mkdir()
    for stem in ["aapl_us_d", "msft_us_d", "goog_us_d"]:
        _write_csv(d / f"{stem}.csv")
    return d


# ---------------------------------------------------------------------------
# load_data — happy path
# ---------------------------------------------------------------------------

def test_loads_all_tickers(universe_dir):
    bundle = load_data(universe_dir)
    assert set(bundle.tickers_loaded) == {"AAPL", "MSFT", "GOOG"}


def test_data_dict_keys_match_tickers_loaded(universe_dir):
    bundle = load_data(universe_dir)
    assert set(bundle.data_dict.keys()) == set(bundle.tickers_loaded)


def test_dataframe_has_close_column(universe_dir):
    bundle = load_data(universe_dir)
    for df in bundle.data_dict.values():
        assert "Close" in df.columns


def test_dataframe_index_is_datetimeindex(universe_dir):
    bundle = load_data(universe_dir)
    for df in bundle.data_dict.values():
        assert isinstance(df.index, pd.DatetimeIndex)


def test_dataframe_has_ticker_column(universe_dir):
    bundle = load_data(universe_dir)
    assert bundle.data_dict["AAPL"]["ticker"].iloc[0] == "AAPL"


def test_no_warnings_on_clean_load(universe_dir):
    bundle = load_data(universe_dir)
    assert bundle.warnings == []


def test_row_count_matches_csv(universe_dir):
    bundle = load_data(universe_dir)
    assert len(bundle.data_dict["AAPL"]) == 50


# ---------------------------------------------------------------------------
# load_data — error handling
# ---------------------------------------------------------------------------

def test_missing_directory_returns_warning(tmp_path):
    bundle = load_data(tmp_path / "does_not_exist")
    assert bundle.data_dict == {}
    assert bundle.warnings


def test_empty_directory_returns_warning(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    bundle = load_data(d)
    assert bundle.data_dict == {}
    assert bundle.warnings


def test_empty_csv_skipped_with_warning(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_csv(d / "good_us_d.csv")
    (d / "empty_us_d.csv").write_text("Date,Open,High,Low,Close,Volume\n")  # header only
    bundle = load_data(d)
    assert "GOOD" in bundle.data_dict
    assert "EMPTY" not in bundle.data_dict
    assert any("empty" in w.lower() for w in bundle.warnings)


def test_csv_without_close_column_skipped(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_csv(d / "good_us_d.csv")
    (d / "bad_us_d.csv").write_text("Date,Open\n2020-01-01,100\n")
    bundle = load_data(d)
    assert "GOOD" in bundle.data_dict
    assert "BAD" not in bundle.data_dict
    assert any("Close" in w for w in bundle.warnings)


def test_partial_load_continues_on_error(tmp_path):
    d = tmp_path / "uni"
    d.mkdir()
    _write_csv(d / "good_us_d.csv")
    (d / "bad_us_d.csv").write_text("not,valid,csv\n!!!")
    bundle = load_data(d)
    # good file still loaded
    assert "GOOD" in bundle.data_dict
    assert bundle.warnings  # warning about bad file
