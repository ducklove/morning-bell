from __future__ import annotations

import time
from typing import Any

import httpx

from polymarket_briefing.config import PolymarketSettings


class PolymarketClient:
    def __init__(self, settings: PolymarketSettings):
        self.settings = settings
        self._client = httpx.Client(timeout=settings.request_timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PolymarketClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self._client.get(url, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        "retryable status",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(self.settings.backoff_seconds * (2**attempt))
        raise RuntimeError(f"Polymarket request failed: {url}") from last_error

    def get_event_by_slug(self, slug: str) -> dict[str, Any]:
        primary = f"{self.settings.gamma_base_url.rstrip('/')}/events/slug/{slug}"
        try:
            data = self._get_json(primary)
        except RuntimeError:
            fallback = f"{self.settings.gamma_base_url.rstrip('/')}/events"
            data = self._get_json(fallback, {"slug": slug})
            if isinstance(data, list) and data:
                data = data[0]
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected event payload for slug {slug}")
        return data

    def list_active_events(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        url = f"{self.settings.gamma_base_url.rstrip('/')}/events"
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }
        data = self._get_json(url, params)
        if isinstance(data, dict):
            data = data.get("events", data.get("data", []))
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_price_history(
        self, token_id: str, start_ts: int, end_ts: int, interval: str = "1d"
    ) -> dict[str, Any]:
        url = f"{self.settings.clob_base_url.rstrip('/')}/prices-history"
        data = self._get_json(
            url,
            {"market": token_id, "startTs": start_ts, "endTs": end_ts, "interval": interval},
        )
        return data if isinstance(data, dict) else {}
