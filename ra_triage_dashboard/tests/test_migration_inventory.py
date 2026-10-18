import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pytest

SCRIPT = Path(__file__).parents[1] / 'scripts/migration_inventory.py'
spec = importlib.util.spec_from_file_location('migration_inventory', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_symlink_is_recorded_without_traversal_and_hardlinks_counted(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'file.bin').write_bytes(b'payload')
    os.link(source / 'file.bin', source / 'linked.bin')
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'secret').write_text('must not scan')
    (source / 'escape').symlink_to(outside, target_is_directory=True)
    result = module.inventory({'roots': [{'id': 'media', 'path': str(source)}]}, tmp_path / 'out', 'all')
    rows = [json.loads(x) for x in (tmp_path / 'out/files.jsonl').read_text().splitlines()]
    assert result['unique_source_inode_bytes'] == 7
    assert result['roots'][0]['logical_bytes'] == 14
    assert len(rows) == 3
    assert next(r for r in rows if r['type'] == 'symlink')['resolved_target'] == str(outside)
    assert all(r['sha256'] == hashlib.sha256(b'payload').hexdigest() for r in rows if r['type'] == 'file')


def test_missing_root_is_an_explicit_error(tmp_path):
    result = module.inventory({'roots': [{'id': 'missing', 'path': str(tmp_path / 'missing')}]}, tmp_path / 'out')
    assert result['errors'] == 1
    assert result['roots'][0]['errors'] == 1


def test_never_invent_payload_digest_or_scan_own_output(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'video.mp4').write_bytes(b'video')
    module.inventory({'roots': [{'id': 'media', 'path': str(source)}]}, tmp_path / 'out')
    assert json.loads((tmp_path / 'out/files.jsonl').read_text())['sha256'] is None
    with pytest.raises(ValueError):
        module.inventory({'roots': [{'id': 'media', 'path': str(source)}]}, source / 'out')
    with pytest.raises(FileExistsError):
        module.inventory({'roots': [{'id': 'media', 'path': str(source)}]}, tmp_path / 'out')
