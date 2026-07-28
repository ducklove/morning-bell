import httpx
import pytest

from polymarket_briefing.config import PolymarketSettings
from polymarket_briefing.polymarket_client import PolymarketClient

GAMMA = "https://gamma-test.example"
RETRYABLE_STATUSES = [429, 500, 502, 503, 504]


def _settings(max_retries: int = 2, backoff_seconds: float = 0.25) -> PolymarketSettings:
    return PolymarketSettings(
        gamma_base_url=GAMMA,
        clob_base_url="https://clob-test.example",
        request_timeout_seconds=1,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
    )


@pytest.fixture
def sleep_calls(monkeypatch):
    """Record backoff durations instead of sleeping, so retry tests stay instant."""
    recorded: list[float] = []
    monkeypatch.setattr(
        "polymarket_briefing.polymarket_client.time.sleep",
        lambda seconds: recorded.append(seconds),
    )
    return recorded


@pytest.mark.parametrize("status", RETRYABLE_STATUSES)
def test_get_json_retries_retryable_status_then_succeeds(httpx_mock, sleep_calls, status):
    httpx_mock.add_response(url=f"{GAMMA}/probe", status_code=status)
    httpx_mock.add_response(url=f"{GAMMA}/probe", json={"ok": True, "value": 42})

    with PolymarketClient(_settings()) as client:
        data = client._get_json(f"{GAMMA}/probe")

    assert data == {"ok": True, "value": 42}
    assert len(httpx_mock.get_requests()) == 2
    assert sleep_calls == [0.25]


def test_get_json_returns_payload_without_retrying_on_first_success(httpx_mock, sleep_calls):
    httpx_mock.add_response(url=f"{GAMMA}/probe?limit=5", json=[{"id": "a"}])

    with PolymarketClient(_settings()) as client:
        data = client._get_json(f"{GAMMA}/probe", {"limit": 5})

    assert data == [{"id": "a"}]
    assert len(httpx_mock.get_requests()) == 1
    assert sleep_calls == []


def test_get_json_gives_up_immediately_on_a_non_retryable_status(httpx_mock, sleep_calls):
    """A 404 is a permanent answer, so it must cost exactly one request.

    Retrying it cannot change the outcome and each round sleeps the full
    backoff, which delayed `get_event_by_slug`'s fallback endpoint by ~10s per
    dead slug with the default settings.
    """
    httpx_mock.add_response(url=f"{GAMMA}/missing", status_code=404)

    with (
        PolymarketClient(_settings(max_retries=3)) as client,
        pytest.raises(RuntimeError) as excinfo,
    ):
        client._get_json(f"{GAMMA}/missing")

    assert len(httpx_mock.get_requests()) == 1
    assert sleep_calls == []
    assert isinstance(excinfo.value.__cause__, httpx.HTTPStatusError)
    assert excinfo.value.__cause__.response.status_code == 404


def test_get_json_still_retries_429_which_is_retryable(httpx_mock, sleep_calls):
    httpx_mock.add_response(url=f"{GAMMA}/busy", status_code=429)
    httpx_mock.add_response(url=f"{GAMMA}/busy", json={"ok": True})

    with PolymarketClient(_settings(max_retries=3)) as client:
        assert client._get_json(f"{GAMMA}/busy") == {"ok": True}

    assert len(httpx_mock.get_requests()) == 2
    assert sleep_calls == [0.25]


def test_get_json_exhausts_max_retries_and_chains_original_error(httpx_mock, sleep_calls):
    for _ in range(3):
        httpx_mock.add_response(url=f"{GAMMA}/flaky", status_code=503)

    with (
        PolymarketClient(_settings(max_retries=2)) as client,
        pytest.raises(RuntimeError) as excinfo,
    ):
        client._get_json(f"{GAMMA}/flaky")

    assert len(httpx_mock.get_requests()) == 3
    assert len(sleep_calls) == 2
    assert str(excinfo.value) == f"Polymarket request failed: {GAMMA}/flaky"

    cause = excinfo.value.__cause__
    assert isinstance(cause, httpx.HTTPStatusError)
    assert cause.response.status_code == 503


def test_get_json_treats_invalid_json_as_retryable(httpx_mock, sleep_calls):
    for _ in range(2):
        httpx_mock.add_response(url=f"{GAMMA}/html", text="<html>maintenance</html>")

    with (
        PolymarketClient(_settings(max_retries=1)) as client,
        pytest.raises(RuntimeError) as excinfo,
    ):
        client._get_json(f"{GAMMA}/html")

    # A 200 with an unparseable body raises ValueError, which the retry clause catches.
    assert len(httpx_mock.get_requests()) == 2
    assert sleep_calls == [0.25]
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_get_json_recovers_after_invalid_json(httpx_mock, sleep_calls):
    httpx_mock.add_response(url=f"{GAMMA}/html", text="not json at all")
    httpx_mock.add_response(url=f"{GAMMA}/html", json={"recovered": True})

    with PolymarketClient(_settings()) as client:
        data = client._get_json(f"{GAMMA}/html")

    assert data == {"recovered": True}
    assert len(httpx_mock.get_requests()) == 2


def test_get_json_backoff_grows_exponentially(httpx_mock, sleep_calls):
    settings = _settings(max_retries=3, backoff_seconds=0.25)
    for _ in range(settings.max_retries + 1):
        httpx_mock.add_response(url=f"{GAMMA}/down", status_code=500)

    with PolymarketClient(settings) as client, pytest.raises(RuntimeError):
        client._get_json(f"{GAMMA}/down")

    assert len(httpx_mock.get_requests()) == settings.max_retries + 1
    # backoff_seconds * 2 ** attempt, and no sleep after the final attempt.
    assert sleep_calls == [0.25, 0.5, 1.0]
    assert sleep_calls == [
        settings.backoff_seconds * (2**attempt) for attempt in range(settings.max_retries)
    ]


def test_get_event_by_slug_returns_primary_payload(httpx_mock, sleep_calls):
    httpx_mock.add_response(url=f"{GAMMA}/events/slug/us-election", json={"id": "1", "slug": "x"})

    with PolymarketClient(_settings()) as client:
        event = client.get_event_by_slug("us-election")

    assert event == {"id": "1", "slug": "x"}
    assert len(httpx_mock.get_requests()) == 1
    assert sleep_calls == []


def test_get_event_by_slug_falls_back_to_query_endpoint(httpx_mock, sleep_calls):
    httpx_mock.add_response(url=f"{GAMMA}/events/slug/us-election", status_code=500)
    httpx_mock.add_response(url=f"{GAMMA}/events?slug=us-election", json={"id": "2"})

    with PolymarketClient(_settings(max_retries=0)) as client:
        event = client.get_event_by_slug("us-election")

    assert event == {"id": "2"}
    requests = httpx_mock.get_requests()
    assert [str(request.url) for request in requests] == [
        f"{GAMMA}/events/slug/us-election",
        f"{GAMMA}/events?slug=us-election",
    ]


def test_get_event_by_slug_unwraps_first_element_of_fallback_list(httpx_mock, sleep_calls):
    httpx_mock.add_response(url=f"{GAMMA}/events/slug/us-election", status_code=404)
    httpx_mock.add_response(
        url=f"{GAMMA}/events?slug=us-election",
        json=[{"id": "first"}, {"id": "second"}],
    )

    with PolymarketClient(_settings(max_retries=0)) as client:
        event = client.get_event_by_slug("us-election")

    assert event == {"id": "first"}
    assert len(httpx_mock.get_requests()) == 2


def test_get_event_by_slug_raises_when_payload_is_not_a_dict(httpx_mock, sleep_calls):
    # The primary endpoint succeeds, so the list is never unwrapped: only the
    # fallback branch does that.
    httpx_mock.add_response(url=f"{GAMMA}/events/slug/us-election", json=[{"id": "1"}])

    with PolymarketClient(_settings()) as client, pytest.raises(RuntimeError) as excinfo:
        client.get_event_by_slug("us-election")

    assert str(excinfo.value) == "Unexpected event payload for slug us-election"
    assert len(httpx_mock.get_requests()) == 1


def test_get_event_by_slug_raises_when_fallback_returns_empty_list(httpx_mock, sleep_calls):
    httpx_mock.add_response(url=f"{GAMMA}/events/slug/ghost", status_code=404)
    httpx_mock.add_response(url=f"{GAMMA}/events?slug=ghost", json=[])

    with (
        PolymarketClient(_settings(max_retries=0)) as client,
        pytest.raises(RuntimeError) as excinfo,
    ):
        client.get_event_by_slug("ghost")

    assert str(excinfo.value) == "Unexpected event payload for slug ghost"
    assert len(httpx_mock.get_requests()) == 2


def _events_page(start: int, count: int) -> list[dict]:
    return [{"id": str(index), "slug": f"e{index}"} for index in range(start, start + count)]


def test_list_active_events_pages_beyond_the_hundred_item_cap(httpx_mock):
    """Gamma caps one response at 100, so 300 must be assembled from pages."""
    httpx_mock.add_response(json=_events_page(0, 100))
    httpx_mock.add_response(json=_events_page(100, 100))
    httpx_mock.add_response(json=_events_page(200, 100))

    with PolymarketClient(_settings()) as client:
        events = client.list_active_events(limit=300, page_size=100)

    assert len(events) == 300
    offsets = [request.url.params.get("offset") for request in httpx_mock.get_requests()]
    assert offsets == ["0", "100", "200"]


def test_list_active_events_stops_on_a_short_page(httpx_mock):
    httpx_mock.add_response(json=_events_page(0, 40))

    with PolymarketClient(_settings()) as client:
        events = client.list_active_events(limit=300, page_size=100)

    assert len(events) == 40
    assert len(httpx_mock.get_requests()) == 1


def test_list_active_events_dedupes_repeats_across_pages(httpx_mock):
    # Volume ordering can shift between requests and repeat an event.
    httpx_mock.add_response(json=_events_page(0, 100))
    httpx_mock.add_response(json=_events_page(50, 100))
    httpx_mock.add_response(json=[])

    with PolymarketClient(_settings()) as client:
        events = client.list_active_events(limit=200, page_size=100)

    slugs = [event["slug"] for event in events]
    assert len(slugs) == len(set(slugs))
    assert len(slugs) == 150


def test_list_active_events_advances_offset_by_page_length_not_kept_count(httpx_mock):
    """A fully duplicate page must still move the cursor, or paging never ends."""
    httpx_mock.add_response(json=_events_page(0, 100))
    httpx_mock.add_response(json=_events_page(0, 100))
    httpx_mock.add_response(json=_events_page(100, 100))
    httpx_mock.add_response(json=[])

    with PolymarketClient(_settings()) as client:
        events = client.list_active_events(limit=300, page_size=100)

    offsets = [request.url.params.get("offset") for request in httpx_mock.get_requests()]
    assert offsets == ["0", "100", "200", "300"]
    assert len(events) == 200


def test_list_active_events_never_requests_more_than_the_cap(httpx_mock):
    httpx_mock.add_response(json=_events_page(0, 10))

    with PolymarketClient(_settings()) as client:
        client.list_active_events(limit=50, page_size=500)

    assert httpx_mock.get_requests()[0].url.params.get("limit") == "50"
