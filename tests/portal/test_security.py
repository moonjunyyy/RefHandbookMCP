from portal.security import Throttle


def test_throttle_reaps_expired_account_keys(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("portal.security.time.monotonic", lambda: now[0])
    throttle = Throttle(limit=2, window=10)
    throttle.fail("old")
    now[0] = 11.0
    for i in range(256):
        throttle.fail(f"new-{i}")
    assert "old" not in throttle._fails
    assert throttle.blocked("new-255") is False
    throttle.fail("new-255")
    assert throttle.blocked("new-255") is True
