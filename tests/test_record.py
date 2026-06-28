import pandas as pd
import pytest

from space_flight.game.record import Record


@pytest.fixture
def record():
    return Record()


def test_record_initial_data_empty(record):
    assert record.data == []


def test_new_time_appends_entry(record):
    record.new_time(1.0)
    assert len(record.data) == 1
    assert record.data[0]["time_s"] == 1.0


def test_new_time_multiple_entries(record):
    record.new_time(0.0)
    record.new_time(1.0)
    record.new_time(2.0)
    assert len(record.data) == 3
    assert record.data[2]["time_s"] == 2.0


def test_record_adds_variable_to_latest_entry(record):
    record.new_time(0.5)
    record.record("speed", 42.0)
    assert record.data[0]["speed"] == 42.0


def test_record_multiple_variables_same_timestep(record):
    record.new_time(1.0)
    record.record("x", 1.0)
    record.record("y", 2.0)
    record.record("label", "foo")
    assert record.data[0]["x"] == 1.0
    assert record.data[0]["y"] == 2.0
    assert record.data[0]["label"] == "foo"


def test_record_only_goes_to_latest_timestep(record):
    record.new_time(0.0)
    record.record("a", 10)
    record.new_time(1.0)
    record.record("b", 20)
    assert "b" not in record.data[0]
    assert "a" not in record.data[1]


def test_save_creates_parquet_file(record, tmp_path):
    record.new_time(0.0)
    record.record("value", 3.14)
    record.filepath = tmp_path / "test_record.parquet"
    record.save()
    assert (tmp_path / "test_record.parquet").exists()
    df = pd.read_parquet(tmp_path / "test_record.parquet")
    assert "time_s" in df.columns
    assert "value" in df.columns
    assert df["value"].iloc[0] == pytest.approx(3.14)


def test_save_multiple_rows(record, tmp_path):
    for i in range(5):
        record.new_time(float(i))
        record.record("step", i)
    record.filepath = tmp_path / "multi.parquet"
    record.save()
    df = pd.read_parquet(tmp_path / "multi.parquet")
    assert len(df) == 5
    assert list(df["time_s"]) == [0.0, 1.0, 2.0, 3.0, 4.0]
