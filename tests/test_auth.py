"""TokenManager refresh logic, tested with a fake HTTP session and a fake clock.

No network is touched: the session records the calls it receives and hands
back canned responses, and the clock is a number we advance by hand.
"""

from flighttrack.auth import REFRESH_MARGIN_S, TokenManager


class FakeResponse:
    def __init__(self, token, expires_in=1800):
        self._payload = {"access_token": token, "expires_in": expires_in}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = 0

    def post(self, url, data, timeout):
        self.calls += 1
        assert data["grant_type"] == "client_credentials"
        assert data["client_id"] == "id" and data["client_secret"] == "secret"
        return FakeResponse(f"token-{self.calls}")


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def make():
    session, clock = FakeSession(), FakeClock()
    return TokenManager("id", "secret", session=session, clock=clock), session, clock


def test_first_call_fetches_a_token():
    manager, session, _ = make()
    assert manager.get_token() == "token-1"
    assert session.calls == 1


def test_second_call_reuses_the_token():
    manager, session, _ = make()
    first = manager.get_token()
    second = manager.get_token()
    assert first == second
    assert session.calls == 1


def test_token_is_refreshed_before_it_expires():
    manager, session, clock = make()
    manager.get_token()
    # Just inside the refresh margin: 1800s lifetime, refresh at 1770s.
    clock.now += 1800 - REFRESH_MARGIN_S + 1
    assert manager.get_token() == "token-2"
    assert session.calls == 2


def test_token_is_not_refreshed_just_before_the_margin():
    manager, session, clock = make()
    manager.get_token()
    clock.now += 1800 - REFRESH_MARGIN_S - 1
    assert manager.get_token() == "token-1"
    assert session.calls == 1


def test_invalidate_forces_a_refetch():
    manager, session, _ = make()
    manager.get_token()
    manager.invalidate()
    assert manager.get_token() == "token-2"
    assert session.calls == 2


def test_auth_headers_carry_bearer_token():
    manager, _, _ = make()
    assert manager.auth_headers() == {"Authorization": "Bearer token-1"}


def test_from_env_returns_none_without_credentials(monkeypatch):
    monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    monkeypatch.chdir("tests")  # no .env here
    assert TokenManager.from_env() is None
