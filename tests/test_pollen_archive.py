"""The archiving interface and its first implementation, TarArchiver.

Bundles queued items into one uncompressed tar whose members are named by their
canonical v1 keys, shipped to v2/archives/<group>/<group>_<ts>.tar -- the same shape the
backend ingestion branches consume.
"""
import tarfile

from bugcam.pollen.archive import ArchiveArtifact, Archiver, TarArchiver
from bugcam.pollen.store import UploadRow, UploadStatus


def _row(staging_path, s3_key, kind="result") -> UploadRow:
    return UploadRow(
        id=0, staging_path=str(staging_path), kind=kind, s3_key=s3_key,
        status=UploadStatus.PENDING, metadata={}, upload_id=None, parts=[], size=None, attempts=0,
    )


def _make_items(tmp_path):
    a = tmp_path / "a.json"
    a.write_bytes(b'{"tracks":[{"track_id":"t1"}]}')
    b = tmp_path / "b.jpg"
    b.write_bytes(b"cropbytes")
    return [
        _row(a, "v1/flick1/20260204_120000/results.json"),
        _row(b, "v1/flick1/20260204_120000/crops/t1/frame_000000.jpg", kind="result"),
    ]


class TestTarArchiver:
    def test_is_an_archiver(self):
        assert issubclass(TarArchiver, Archiver)

    def test_pack_produces_self_describing_tar(self, tmp_path):
        items = _make_items(tmp_path)
        staging = tmp_path / "staging"
        archiver = TarArchiver()

        artifact = archiver.pack("flick1", items, staging, timestamp="20260204_130000")

        assert isinstance(artifact, ArchiveArtifact)
        assert artifact.s3_key == "v2/archives/flick1/flick1_20260204_130000.tar"
        assert artifact.path.exists()
        assert artifact.member_keys == [it.s3_key for it in items]

        with tarfile.open(artifact.path) as tar:
            names = sorted(tar.getnames())
            assert names == sorted(it.s3_key for it in items)
            # member bytes match the source files
            extracted = tar.extractfile("v1/flick1/20260204_120000/results.json").read()
            assert extracted == b'{"tracks":[{"track_id":"t1"}]}'

    def test_pack_empty_returns_none(self, tmp_path):
        assert TarArchiver().pack("flick1", [], tmp_path / "s", timestamp="20260204_130000") is None

    def test_custom_prefix(self, tmp_path):
        items = _make_items(tmp_path)
        archiver = TarArchiver(archive_key_prefix="v2/batches")
        artifact = archiver.pack("dot1", items, tmp_path / "s", timestamp="20260204_130000")
        assert artifact.s3_key == "v2/batches/dot1/dot1_20260204_130000.tar"
