def test_offline_fixture_exercises_real_broker_overlap_and_retry():
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.acceptance.perf_provider_fixture import run
    result = run(ProviderService)
    assert result['passed'] and result['real_broker_overlap'] == 4
    assert result['paid_requests'] == 0
