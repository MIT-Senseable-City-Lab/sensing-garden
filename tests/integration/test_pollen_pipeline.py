"""The high-level Pollen pipeline (build_pollen -> enqueue -> flush) against the
real backend + ministack S3: a produced file lands in S3 and is cleaned up.
"""
from __future__ import annotations

import pytest

from bugcam.pollen.integration import build_pollen

pytestmark = pytest.mark.integration

DEVICE_ID = "FLIK2"  # the authenticated device behind the seeded device api key


def test_enqueue_and_flush_uploads_and_cleans_up(presign_url, device_api_key, s3_key, tmp_path, fetch_object):
    out = tmp_path / "out"
    pol = build_pollen(out, presign_url, device_api_key, state_dir=tmp_path / "state")

    hb = out / DEVICE_ID / "heartbeats" / "20260204_120000.json"
    hb.parent.mkdir(parents=True)
    hb.write_text('{"device_id":"FLIK2"}', encoding="utf-8")

    pol.enqueue(hb, "heartbeat")
    pol.flush()

    key = f"v1/{DEVICE_ID}/heartbeats/20260204_120000.json"
    assert fetch_object(key) == b'{"device_id":"FLIK2"}'
    assert not hb.exists()                      # delete_after_upload default
    assert pol.store.pending_count() == 0
