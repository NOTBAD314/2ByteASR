"""Only owned tiny files; exercise the frozen audit's real-data write gates."""
import pytest
from tests.test_storage_maintenance_ui import service
from twobyteasr.acceptance.real_storage_after_audit import readonly_service,small_file_fingerprint


def test_real_after_service_reads_without_touching_db_and_blocks_all_mutations(service):
    cache=service.paths.cache_root/'preview.png';cache.write_bytes(b'owned tiny preview')
    assert service.register(cache,'preview',producer='isolated_after_audit_fixture')
    before=small_file_fingerprint(service.db_path)
    readonly=readonly_service(service.paths)
    scan=readonly.scan(include_models=False)
    assert scan.complete and scan.total_bytes==len(b'owned tiny preview')
    assert small_file_fingerprint(service.db_path)==before
    item=next(i for i in scan.items if i.path==str(cache))
    for operation in (lambda:readonly._db(),lambda:readonly._registered(),lambda:readonly.save_policy({}),
        lambda:readonly.write_state_json('last-cleanup.json',{}),lambda:readonly.clean([item]),
        lambda:readonly.register(cache,'preview',producer='test'),lambda:readonly.touch(cache)):
        with pytest.raises(PermissionError):operation()
    with pytest.raises(PermissionError):
        with readonly.lease(cache):pass
    assert len(readonly.rejected_actions)==8
    assert small_file_fingerprint(service.db_path)==before and cache.read_bytes()==b'owned tiny preview'
    assert not (service.state_root/'last-cleanup.json').exists() and not service.policy_path.exists()
