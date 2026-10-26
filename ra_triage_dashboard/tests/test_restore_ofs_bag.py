import gzip
import hashlib
import importlib.util
import struct
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location(
    "restore_ofs_bag", Path(__file__).parents[1] / "scripts/restore_ofs_bag.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(tmp_path):
    def fields(values):
        parts = [key.encode() + b"=" + value for key, value in values.items()]
        return b"".join(struct.pack("<I", len(part)) + part for part in parts)

    def record(header, data=b""):
        head = fields(header)
        return struct.pack("<I", len(head)) + head + struct.pack("<I", len(data)) + data

    magic = b"#ROSBAG V2.0\n"
    header = record({"op": b"\x03", "index_pos": struct.pack("<Q", 0)})
    header = record(
        {"op": b"\x03", "index_pos": struct.pack("<Q", len(magic) + len(header))}
    )
    connection = record(
        {
            "op": b"\x07",
            "conn": struct.pack("<I", 0),
            "topic": b"/planning/planning_debug",
        },
        fields({"type": b"proto_msg/PlanningDebug"}),
    )
    chunks = record(
        {
            "op": b"\x06",
            "start_time": struct.pack("<II", 0, 1000000),
            "end_time": struct.pack("<II", 0, 2000000),
            "count": struct.pack("<I", 1),
        },
        struct.pack("<II", 0, 50),
    )
    data = magic + header + connection + chunks
    mount = tmp_path / "mount"
    archive = next(iter(m.ARCHIVES))
    p = mount / archive / "test.bag.gz"
    p.parent.mkdir(parents=True)
    p.write_bytes(gzip.compress(data))
    row = {
        "issue_id": "cn1",
        "trip_id": "trip1",
        "topic": "/planning/planning_debug",
        "requested_start_ms": 1,
        "requested_end_ms": 2,
        "ofs_path": m.PREFIX + archive + "/test.bag.gz",
        "original_sha256": hashlib.sha256(data).hexdigest(),
        "original_bytes": len(data),
        "compressed_bytes": p.stat().st_size,
    }
    return row, mount, data


def test_restore_hash_and_no_overwrite(tmp_path):
    row, mount, data = fixture(tmp_path)
    r = m.restore(row, mount, tmp_path / "scratch", 1024**2)
    assert Path(r["path"]).read_bytes() == data
    assert r["actual_topic_window_verified"] is True
    assert r["connections"][0]["messages"] == 50
    with pytest.raises(FileExistsError):
        m.restore(row, mount, tmp_path / "scratch", 1024**2)


def test_identity_requires_trip_topic_and_exact_window(tmp_path):
    row, _, _ = fixture(tmp_path)
    assert m.select([row], "cn1", "trip1", "/planning/planning_debug", 1, 2) == row
    with pytest.raises(ValueError):
        m.select([row], "cn1", "other", "/planning/planning_debug", 1, 2)
    with pytest.raises(ValueError):
        m.select([row], "cn1", "trip1", "/planning/planning_debug", 0, 2)


def test_corrupt_digest_never_publishes_payload(tmp_path):
    row, mount, _ = fixture(tmp_path)
    row["original_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        m.restore(row, mount, tmp_path / "scratch", 1024**2)
    assert list((tmp_path / "scratch").glob("*.bag")) == []
    assert list((tmp_path / "scratch").glob("*.partial")) == []


def test_path_traversal_and_archive_escape_rejected(tmp_path):
    row, mount, _ = fixture(tmp_path)
    bad = {**row, "ofs_path": m.PREFIX + next(iter(m.ARCHIVES)) + "/../../secret"}
    with pytest.raises(ValueError):
        m.archive_path(bad, mount)
    p = m.archive_path(row, mount)
    p.unlink()
    outside = tmp_path / "secret"
    outside.write_text("secret")
    p.symlink_to(outside)
    with pytest.raises(ValueError):
        m.archive_path(row, mount)


def test_registered_size_enforces_scratch_budget(tmp_path):
    row, mount, _ = fixture(tmp_path)
    with pytest.raises(ValueError):
        m.restore(row, mount, tmp_path / "scratch", 1)


@pytest.mark.parametrize(
    "change", [{"topic": "/other"}, {"requested_start_ms": 2}, {"requested_end_ms": 1}]
)
def test_actual_index_must_match_request_before_publication(tmp_path, change):
    row, mount, _ = fixture(tmp_path)
    with pytest.raises(ValueError):
        m.restore({**row, **change}, mount, tmp_path / "scratch", 1024**2)
    assert list((tmp_path / "scratch").glob("*.bag")) == []


def test_truncated_ros_index_rejected(tmp_path):
    row, mount, data = fixture(tmp_path)
    path = tmp_path / "truncated.bag"
    path.write_bytes(data[:-1])
    with pytest.raises(ValueError):
        m.inspect_index(path, row)


def test_archive_root_symlink_cannot_escape_mount(tmp_path):
    row, mount, _ = fixture(tmp_path)
    archive = Path(row["ofs_path"][len(m.PREFIX) :]).parts[0]
    outside = tmp_path / "outside-archive"
    (mount / archive).rename(outside)
    (mount / archive).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        m.archive_path(row, mount)
