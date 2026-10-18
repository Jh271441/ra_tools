import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('migration_media', Path(__file__).parents[1] / 'scripts/verify_migration_media.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    payload = b'migration verified bytes'
    (target / 'video.mp4').write_bytes(payload)
    row = {'root_id': 'batch', 'relative_path': 'video.mp4', 'type': 'file',
           'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'stable_during_read': True}
    manifest = tmp_path / 'manifest.jsonl'
    manifest.write_text(json.dumps(row) + '\n')
    return target, manifest, row


def test_complete_batch(tmp_path):
    target, manifest, row = fixture(tmp_path)
    result = module.verify(manifest, 'batch', target)
    assert result['all_verified'] and result['verified_files'] == 1
    assert result['verified_bytes'] == row['size']


@pytest.mark.parametrize('damage', ['missing', 'truncated', 'corrupt', 'extra', 'escape'])
def test_damaged_batch_never_publishes(tmp_path, damage):
    target, manifest, row = fixture(tmp_path)
    video = target / 'video.mp4'
    if damage == 'missing':
        video.unlink()
    elif damage == 'truncated':
        video.write_bytes(b'x')
    elif damage == 'corrupt':
        video.write_bytes(b'x' * row['size'])
    elif damage == 'extra':
        (target / 'untracked.mp4').write_bytes(b'new')
    else:
        outside = tmp_path / 'outside'
        outside.write_bytes(video.read_bytes())
        video.unlink()
        video.symlink_to(outside)
    assert not module.verify(manifest, 'batch', target)['all_verified']


def test_unstable_or_wrong_manifest_rejected(tmp_path):
    target, manifest, row = fixture(tmp_path)
    assert not module.verify(manifest, 'wrong-batch', target)['all_verified']
    row['stable_during_read'] = False
    manifest.write_text(json.dumps(row) + '\n')
    assert not module.verify(manifest, 'batch', target)['all_verified']
