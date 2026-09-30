"""OAuth2 client-credentials authentication for the OpenSky Network API.

OpenSky no longer accepts username/password.  You register an API client on
your account page, get a client_id and client_secret, and exchange them for a
bearer token that lasts 30 minutes.  TokenManager does that exchange and
refreshes the token shortly before it expires so a long collection run never
stalls on a 401.
"""

import os
import time

import requests
from dotenv import load_dotenv

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
# Refresh this many seconds before the token would actually expire.
REFRESH_MARGIN_S = 30
# What OpenSky hands out today; used only if the response omits expires_in.
DEFAULT_TOKEN_LIFETIME_S = 30 * 60


class TokenManager:
    """Fetches a bearer token on demand and refreshes it before it expires."""

    def __init__(self, client_id: str, client_secret: str, session=None, clock=time.time):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self._clock = clock  # injectable so tests can fake the passage of time
        self._token = None
        self._expires_at = 0.0
        self.refresh_count = 0

    @classmethod
    def from_env(cls, session=None):
        """Build from OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET in .env or the environment.

        Returns None when credentials are absent so callers can fall back to
        anonymous access (fewer credits, coarser time resolution).
        """
        load_dotenv()
        client_id = os.getenv("OPENSKY_CLIENT_ID", "").strip()
        client_secret = os.getenv("OPENSKY_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None
        return cls(client_id, client_secret, session=session)

    def get_token(self) -> str:
        """Return a valid token, fetching a fresh one if the current one is near expiry."""
        if self._token is None or self._clock() >= self._expires_at - REFRESH_MARGIN_S:
            self._refresh()
        return self._token

    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.get_token()}"}

    def invalidate(self) -> None:
        """Forget the current token.  Call this after a 401 so the next call refetches."""
        self._token = None
        self._expires_at = 0.0

    def _refresh(self) -> None:
        response = self.session.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        lifetime = float(payload.get("expires_in", DEFAULT_TOKEN_LIFETIME_S))
        self._expires_at = self._clock() + lifetime
        self.refresh_count += 1


if __name__ == "__main__":
    # Quick manual check: python -m flighttrack.auth
    manager = TokenManager.from_env()
    if manager is None:
        raise SystemExit("No credentials found. Copy .env.example to .env and fill it in.")
    first = manager.get_token()
    second = manager.get_token()
    print(f"token starts with: {first[:24]}...")
    print(f"second call reused it: {first == second}")
