"""Daily log rollover + completed-log shipping.

The logging mechanism owns the push to the uploader: it rolls to a new dated file
when the day changes and hands the finished file to ``on_complete``; at startup it
ships any non-today logs left behind. The uploader never scans for logs.
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path

from bugcam.log_shipping import DailyLogHandler, ship_existing_logs


class _Clock:
    def __init__(self, day: str) -> None:
        self.value = datetime.strptime(day, "%Y%m%d")

    def __call__(self) -> datetime:
        return self.value

    def set(self, day: str) -> None:
        self.value = datetime.strptime(day, "%Y%m%d")


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def test_rollover_ships_completed_file_and_opens_new_day(tmp_path):
    clock = _Clock("20260101")
    shipped: list[Path] = []
    h = DailyLogHandler(tmp_path, now=clock)
    h.on_complete = shipped.append

    h.emit(_record("day one"))
    assert (tmp_path / "edge26_20260101.log").exists()

    clock.set("20260102")
    h.emit(_record("day two"))

    # the completed (day-one) file was pushed exactly once, and day two is now active
    assert shipped == [tmp_path / "edge26_20260101.log"]
    assert (tmp_path / "edge26_20260102.log").exists()
    assert h._day == "20260102"
    h.close()


def test_no_rollover_when_day_unchanged(tmp_path):
    clock = _Clock("20260101")
    shipped: list[Path] = []
    h = DailyLogHandler(tmp_path, now=clock)
    h.on_complete = shipped.append

    h.emit(_record("a"))
    h.emit(_record("b"))

    assert shipped == []
    h.close()


def test_ship_existing_enqueues_only_completed_logs(tmp_path):
    (tmp_path / "edge26_20260101.log").write_text("done\n")
    (tmp_path / "edge26_20260102.log").write_text("also done\n")
    (tmp_path / "edge26_20260103.log").write_text("active\n")  # today

    shipped: list[Path] = []
    n = ship_existing_logs(shipped.append, tmp_path, now=_Clock("20260103"))

    assert n == 2
    assert sorted(p.name for p in shipped) == ["edge26_20260101.log", "edge26_20260102.log"]


def test_ship_existing_no_logs_is_noop(tmp_path):
    assert ship_existing_logs(lambda p: None, tmp_path / "missing", now=_Clock("20260103")) == 0


def test_rollover_recreates_a_removed_log_dir(tmp_path):
    # An operator (or anything else) can rmtree the log dir out from under a
    # live handler without restarting the process -- the already-open fd keeps
    # accepting writes invisibly, so nothing breaks until the next rollover
    # tries to open a *new* file and finds the directory gone.
    clock = _Clock("20260101")
    h = DailyLogHandler(tmp_path, now=clock)

    shutil.rmtree(tmp_path)
    assert not tmp_path.exists()

    clock.set("20260102")
    h.emit(_record("day two"))  # must not raise

    assert (tmp_path / "edge26_20260102.log").exists()
    assert h._day == "20260102"
    h.close()


def test_rollover_open_failure_does_not_raise_and_retries_next_emit(tmp_path, monkeypatch):
    # If the new day's file still can't be opened (permission error, disk
    # full, ...), emit() must never raise -- a caller's ordinary log call
    # (e.g. picamera2 logging "Camera stopped" mid stop_recording()) must not
    # blow up, and every other thread's next log call must not inherit a
    # permanently broken handler.
    clock = _Clock("20260101")
    shipped: list[Path] = []
    h = DailyLogHandler(tmp_path, now=clock)
    h.on_complete = shipped.append

    clock.set("20260102")
    real_open = h._open
    monkeypatch.setattr(h, "_open", lambda day: (_ for _ in ()).throw(OSError("disk full")))
    h.emit(_record("during outage"))  # must not raise

    assert h._day == "20260101"  # unchanged -- next emit() retries
    assert shipped == []  # not shipped: rollover never actually completed
    assert not (tmp_path / "edge26_20260102.log").exists()

    monkeypatch.setattr(h, "_open", real_open)
    h.emit(_record("outage over"))  # retries and succeeds this time

    assert h._day == "20260102"
    assert shipped == [tmp_path / "edge26_20260101.log"]
    h.close()
