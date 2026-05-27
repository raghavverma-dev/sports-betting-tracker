"""HTTP client for The Odds API.

Lives server-side so the API key never reaches the browser. Raises a
clear `OddsApiError` on non-2xx responses so callers can map to HTTP
statuses without digging through httpx exceptions.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import structlog

from betedge.config import Settings

logger = structlog.get_logger(__name__)


SPORT_KEY_MAP = {
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "NCAAF": "americanfootball_ncaaf",
    "NCAAB": "basketball_ncaab",
    "MLS": "soccer_usa_mls",
    "UFC": "mma_mixed_martial_arts",
}


class OddsApiError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class OddsApiClient:
    def __init__(self, settings: Settings, *, timeout: float = 10.0) -> None:
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.odds_api_base_url,
            timeout=timeout,
            headers={"User-Agent": "betedge/0.1"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OddsApiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _require_key(self) -> str:
        key = self._settings.odds_api_key
        if not key:
            raise OddsApiError(
                "Live odds unavailable: ODDS_API_KEY is not configured on the backend.",
                status_code=503,
            )
        return key

    def _get(self, path: str, params: dict[str, Any]) -> object:
        params = {**params, "apiKey": self._require_key()}
        try:
            resp = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            logger.error("odds_api.network_error", path=path, error=str(exc))
            raise OddsApiError(f"Network error contacting The Odds API: {exc}") from exc

        if resp.status_code == 401:
            raise OddsApiError("Invalid API key for The Odds API.", status_code=502)
        if resp.status_code == 429:
            raise OddsApiError("The Odds API rate limit reached.", status_code=503)
        if not resp.is_success:
            logger.warning("odds_api.non_2xx", path=path, status=resp.status_code)
            raise OddsApiError(
                f"The Odds API returned {resp.status_code}: {resp.text[:200]}",
                status_code=502,
            )
        return resp.json()

    def fetch_odds(self, sport: str, market: str = "h2h") -> list[dict[str, Any]]:
        sport_key = SPORT_KEY_MAP.get(sport)
        if not sport_key:
            raise OddsApiError(f"Unsupported sport: {sport}", status_code=400)
        params = {"regions": "us", "markets": market, "oddsFormat": "american"}
        return cast(list[dict[str, Any]], self._get(f"/sports/{sport_key}/odds/", params))

    def fetch_scores(self, sport: str, days_from: int = 3) -> list[dict[str, Any]]:
        sport_key = SPORT_KEY_MAP.get(sport)
        if not sport_key:
            raise OddsApiError(f"Unsupported sport: {sport}", status_code=400)
        return cast(
            list[dict[str, Any]],
            self._get(f"/sports/{sport_key}/scores/", {"daysFrom": days_from}),
        )
