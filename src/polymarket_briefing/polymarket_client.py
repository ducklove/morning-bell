from __future__ import annotations

import time
from typing import Any

import httpx

from polymarket_briefing.config import PolymarketSettings

# Gamma caps a single /events response at 100 no matter what limit is asked for.
MAX_EVENTS_PER_REQUEST = 100

# Statuses worth asking again about; anything else is a permanent answer.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _event_identity(event: dict[str, Any]) -> str:
    return str(event.get("id") or event.get("slug") or id(event))


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
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                # A 404 or 400 will not become a 200 by asking again, and each
                # pointless round costs a full backoff sleep — with the default
                # settings a dead slug burned ~10s before the caller's fallback
                # endpoint was even tried.
                if exc.response.status_code not in RETRYABLE_STATUS_CODES:
                    break
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

    def list_active_events(
        self,
        limit: int = 100,
        offset: int = 0,
        page_size: int = 100,
        active_only: bool = True,
        include_closed: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch up to `limit` events, paging as needed.

        Gamma silently caps a single /events request at 100 regardless of the
        requested limit, so asking for 300 used to yield 100 and quietly shrink
        the discovery pool to a third of what the config asked for. Page until
        `limit` is reached or the API stops returning new events.
        """
        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        page_size = max(1, min(page_size, MAX_EVENTS_PER_REQUEST))
        # Advance by what the API returned, not by what survived deduping —
        # otherwise a page of all-duplicates would re-request the same window
        # forever.
        cursor = offset
        while len(collected) < limit:
            requested = min(page_size, limit - len(collected))
            page = self._fetch_event_page(
                limit=requested,
                offset=cursor,
                active_only=active_only,
                include_closed=include_closed,
            )
            if not page:
                break
            cursor += len(page)
            # Volume ordering can shift between requests, so a later page may
            # repeat an event already collected.
            fresh = [item for item in page if _event_identity(item) not in seen_ids]
            seen_ids.update(_event_identity(item) for item in page)
            collected.extend(fresh)
            if len(page) < requested:
                break
        return collected[:limit]

    def _fetch_event_page(
        self, limit: int, offset: int, active_only: bool, include_closed: bool
    ) -> list[dict[str, Any]]:
        url = f"{self.settings.gamma_base_url.rstrip('/')}/events"
        params = {
            "limit": limit,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }
        if active_only:
            params["active"] = "true"
        if not include_closed:
            params["closed"] = "false"
        data = self._get_json(url, params)
        if isinstance(data, dict):
            data = data.get("events", data.get("data", []))
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_price_history(
        self, token_id: str, start_ts: int, end_ts: int, interval: str | None = None
    ) -> dict[str, Any]:
        # The CLOB API ignores startTs/endTs and returns a fixed recent window
        # whenever `interval` is present, so omit it to honor the requested range.
        url = f"{self.settings.clob_base_url.rstrip('/')}/prices-history"
        params: dict[str, Any] = {"market": token_id, "startTs": start_ts, "endTs": end_ts}
        if interval:
            params["interval"] = interval
        data = self._get_json(url, params)
        return data if isinstance(data, dict) else {}
