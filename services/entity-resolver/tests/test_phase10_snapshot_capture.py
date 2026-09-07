import pytest

from entity_resolver.service import EntityService


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None


class _HTTP:
    def __init__(self, *, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("temporary capture failure")
        return _Response()


def _service(http):
    service = EntityService.__new__(EntityService)
    service._http = http
    service._phase10_captured_entities = set()
    return service


@pytest.mark.asyncio
async def test_phase10_capture_passes_resolved_entity_and_deduplicates_success():
    http = _HTTP()
    service = _service(http)

    await service._capture_phase10_evidence("mint-1", "entity-1")
    await service._capture_phase10_evidence("mint-1", "entity-1")

    assert len(http.calls) == 1
    url, kwargs = http.calls[0]
    assert url.endswith("/v1/entity-graph/investigation/mint-1/calibration")
    assert kwargs["params"] == {"entity_id": "entity-1"}
    assert ("mint-1", "entity-1") in service._phase10_captured_entities


@pytest.mark.asyncio
async def test_phase10_capture_failure_remains_retryable():
    http = _HTTP(fail_first=True)
    service = _service(http)

    await service._capture_phase10_evidence("mint-2", "entity-2")
    assert ("mint-2", "entity-2") not in service._phase10_captured_entities

    await service._capture_phase10_evidence("mint-2", "entity-2")
    assert len(http.calls) == 2
    assert ("mint-2", "entity-2") in service._phase10_captured_entities


@pytest.mark.asyncio
async def test_phase10_capture_key_includes_entity_identity():
    http = _HTTP()
    service = _service(http)

    await service._capture_phase10_evidence("mint-3", "entity-a")
    await service._capture_phase10_evidence("mint-3", "entity-b")

    assert len(http.calls) == 2
    assert {call[1]["params"]["entity_id"] for call in http.calls} == {"entity-a", "entity-b"}
