from entity_resolver.config import settings

def test_thresholds_sane() -> None:
    assert settings.min_co_buy_overlap >= 2
    assert 0 < settings.deployer_link_confidence <= 1
    assert 0 < settings.co_buy_link_confidence <= 1
    assert settings.co_buy_link_confidence < settings.deployer_link_confidence
