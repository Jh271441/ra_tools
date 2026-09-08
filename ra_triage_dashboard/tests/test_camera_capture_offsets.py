import json
from ra_triage_dashboard.app.assets import CameraIndex


def test_camera_uses_capture_offsets(tmp_path):
    folder = tmp_path / "cn1_1234"
    images = folder / "after_compress"
    images.mkdir(parents=True)
    for i in range(9):
        (images / f"{i}.jpg").write_bytes(b"image")
    (folder / "camera_meta.json").write_text(json.dumps({"offsets_ms": [-19000,-15000,-10000,-5000,0,5000,10000,15000,19000]}))
    frames = CameraIndex(tmp_path).get_assets("cn1",1234)["frames"]
    assert [f["offset_sec"] for f in frames] == [-19,-15,-10,-5,0,5,10,15,19]


def test_invalid_explicit_offsets_do_not_fall_back_to_legacy(tmp_path):
    folder = tmp_path / "cn1_1234"
    (folder / "after_compress").mkdir(parents=True)
    (folder / "after_compress" / "0.jpg").write_bytes(b"image")
    (folder / "camera_meta.json").write_text("invalid")
    assert CameraIndex(tmp_path).get_assets("cn1")["frames"][0]["offset_sec"] is None
