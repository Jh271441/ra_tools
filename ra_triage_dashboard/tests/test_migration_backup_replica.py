import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('replica', Path(__file__).parents[1] / 'scripts/migration_backup_replica.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def generation(base, number=1):
    p = base / ('20261018T000000Z-%08x' % number); p.mkdir(parents=True)
    receipt = {'complete': True, 'restore_verified': True}
    for name, key in m.FILES.items():
        payload = (name + str(number)).encode(); (p / name).write_bytes(payload)
        receipt[key] = hashlib.sha256(payload).hexdigest()
    (p / 'receipt.json').write_text(json.dumps(receipt))
    return p


def test_replica_readback_and_idempotent_publication(tmp_path):
    source = generation(tmp_path / 'local'); remote = tmp_path / 'remote'
    dest = m.publish(source, remote)
    assert m.verified(dest)['off_host_replica_verified'] is True
    assert m.publish(source, remote) == dest
    assert len(list(remote.iterdir())) == 1


def test_corrupt_source_or_remote_never_replaced(tmp_path):
    source = generation(tmp_path / 'local'); remote = tmp_path / 'remote'
    dest = m.publish(source, remote)
    (dest / 'database.dump').write_bytes(b'bad')
    with pytest.raises(ValueError): m.publish(source, remote)
    assert (dest / 'database.dump').read_bytes() == b'bad'


def test_retains_14_verified_pairs_and_preserves_pinned(tmp_path):
    local, remote = tmp_path / 'local', tmp_path / 'remote'
    for n in range(1, 16): m.publish(generation(local, n), remote)
    pinned = local / 'migration-cutover'; pinned.mkdir()
    removed = m.prune(local, remote)
    assert len(removed) == 1 and pinned.is_dir()
    assert len(list(remote.iterdir())) == 14


def test_corrupt_retained_copy_prevents_any_pruning(tmp_path):
    local, remote = tmp_path / 'local', tmp_path / 'remote'
    for n in range(1, 16): dest = m.publish(generation(local, n), remote)
    (dest / 'attachments.tar.gz').write_bytes(b'bad')
    with pytest.raises(ValueError): m.prune(local, remote)
    assert len(list(local.iterdir())) == 15 and len(list(remote.iterdir())) == 15
