"""Local-only adversarial provider streams; no external downloads."""

import gzip

import httpx
import pytest

from app.services import timetable_ingestion as ingestion


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks, failure=None):
        self.chunks = chunks
        self.failure = failure
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk
        if self.failure:
            raise self.failure

    async def aclose(self):
        self.closed = True


def install_provider(monkeypatch, stream, *, headers=None, status=200, limit=64):
    original_client = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, stream=stream)

    monkeypatch.setattr(ingestion.settings, "LIVE_DATA_ENABLED", True)
    monkeypatch.setattr(ingestion.settings, "GTFS_REALTIME_FEED_URL", "https://feed.example/rt")
    monkeypatch.setattr(ingestion.settings, "TIMETABLE_MAX_FEED_BYTES", limit)
    monkeypatch.setattr(
        ingestion.httpx, "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"content-length": "2"}, {"content-length": "invalid"}])
async def test_rejects_chunk_overflow_without_consuming_rest(monkeypatch, headers):
    stream = TrackedStream([b"a" * 32, b"b" * 33, b"never read"])
    install_provider(monkeypatch, stream, headers=headers)
    with pytest.raises(ingestion.TimetableIngestionError) as error:
        await ingestion._download_configured("gtfs_realtime")
    assert error.value.code == "FEED_TOO_LARGE"
    assert stream.read_count == 2
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("length", ["65", "9" * 5000], ids=["oversized", "huge-integer"])
async def test_large_declared_length_rejected_before_body(monkeypatch, length):
    stream = TrackedStream([b"never read"])
    install_provider(monkeypatch, stream, headers={"content-length": length})
    with pytest.raises(ingestion.TimetableIngestionError) as error:
        await ingestion._download_configured("gtfs_realtime")
    assert error.value.code == "FEED_TOO_LARGE"
    assert stream.read_count == 0
    assert stream.closed


@pytest.mark.asyncio
async def test_http_compression_rejected_before_decompression(monkeypatch):
    encoded = gzip.compress(b"a" * 1000)
    assert len(encoded) < 64
    stream = TrackedStream([encoded, b"never read"])
    install_provider(monkeypatch, stream, headers={
        "content-length": str(len(encoded)), "content-encoding": "gzip",
    })
    with pytest.raises(ingestion.TimetableIngestionError) as error:
        await ingestion._download_configured("gtfs_realtime")
    assert error.value.code == "UNSUPPORTED_ENCODING"
    assert stream.read_count == 0
    assert stream.closed


@pytest.mark.asyncio
async def test_exact_limit_preserves_bytes_headers_and_url(monkeypatch):
    stream = TrackedStream([b"a" * 32, b"b" * 32])
    install_provider(monkeypatch, stream, headers={"ETag": '"capture"'})
    payload, url, headers = await ingestion._download_configured("gtfs_realtime")
    assert payload == b"a" * 32 + b"b" * 32
    assert url == "https://feed.example/rt"
    assert headers["etag"] == '"capture"'
    assert stream.closed


@pytest.mark.asyncio
async def test_identity_feed_preserves_hash_and_provenance(monkeypatch):
    import hashlib
    payload = b'{"header":{"gtfs_realtime_version":"2.0"},"entity":[]}'
    stream = TrackedStream([payload])
    requests = install_provider(monkeypatch, stream, headers={"ETag": "v1"})
    feed = await ingestion.fetch_gtfs_realtime()
    assert feed.source.checksum_sha256 == hashlib.sha256(payload).hexdigest()
    assert feed.source.source_url == "https://feed.example/rt"
    assert feed.source.source_version == "v1"
    assert stream.closed
    assert requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, "AUTH_REQUIRED"), (403, "AUTH_REQUIRED"), (500, "UNAVAILABLE")])
async def test_http_errors_close_without_reading_body(monkeypatch, status, code):
    stream = TrackedStream([b"never read"])
    install_provider(monkeypatch, stream, status=status)
    with pytest.raises(ingestion.TimetableIngestionError) as error:
        await ingestion._download_configured("gtfs_realtime")
    assert error.value.code == code
    assert stream.read_count == 0
    assert stream.closed


@pytest.mark.asyncio
async def test_timeout_midstream_preserves_error_contract_and_closes(monkeypatch):
    stream = TrackedStream([b"partial"], failure=httpx.ReadTimeout("fixture timeout"))
    install_provider(monkeypatch, stream)
    with pytest.raises(ingestion.TimetableIngestionError) as error:
        await ingestion._download_configured("gtfs_realtime")
    assert error.value.code == "UNAVAILABLE"
    assert stream.closed


@pytest.mark.asyncio
async def test_empty_response_preserves_error_contract(monkeypatch):
    stream = TrackedStream([])
    install_provider(monkeypatch, stream)
    with pytest.raises(ingestion.TimetableIngestionError) as error:
        await ingestion._download_configured("gtfs_realtime")
    assert error.value.code == "EMPTY_FEED"
    assert stream.closed
