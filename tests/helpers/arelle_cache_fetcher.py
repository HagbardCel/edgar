"""Test helper: serve Arelle package-cache bytes as a ControlledFetcher."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import arelle

from edgar.sec.client import FetchHop, FetchResult, FetchTrace
from edgar.storage.objects import ObjectStore, SizeLimitExceeded
from edgar.xbrl.uri import normalize_uri

_ARELLE_HTTP = Path(arelle.__file__).resolve().parent / "resources" / "cache" / "http"
_ARELLE_HTTPS = Path(arelle.__file__).resolve().parent / "resources" / "cache" / "https"


class ArelleCacheFetcher:
    """Fetch known test URIs from an explicit map, else from Arelle's package cache."""

    def __init__(self, mapping: dict[str, bytes] | None = None) -> None:
        self.mapping = {normalize_uri(k): v for k, v in (mapping or {}).items()}
        self.calls: list[str] = []

    def _bytes_for(self, canonical: str) -> bytes:
        if canonical in self.mapping:
            return self.mapping[canonical]
        if "://" not in canonical:
            raise KeyError(canonical)
        rel = canonical.split("://", 1)[1]
        for base in (_ARELLE_HTTP, _ARELLE_HTTPS):
            path = base / rel
            if path.is_file():
                return path.read_bytes()
        raise KeyError(canonical)

    def fetch_to_store(
        self, url: str, store: ObjectStore, *, max_bytes: int
    ) -> tuple[FetchResult, object]:
        canonical = normalize_uri(url)
        self.calls.append(canonical)
        data = self._bytes_for(canonical)
        if len(data) > max_bytes:
            raise SizeLimitExceeded(f"exceeded max_bytes={max_bytes}")
        obj = store.put_bytes(data)
        observed_at = datetime.now(UTC)
        trace = FetchTrace(
            requested_uri=url,
            hops=(
                FetchHop(
                    uri=canonical,
                    resolved_candidates=("1.2.3.4",),
                    pinned_ip="1.2.3.4",
                    peer_ip="1.2.3.4",
                    http_status=200,
                    error=None,
                    observed_at=observed_at,
                ),
            ),
            final_uri=canonical,
            content_sha256=obj.sha256,
            byte_size=obj.byte_size,
        )
        result = FetchResult(
            requested_uri=url,
            final_uri=canonical,
            status_code=200,
            headers={},
            redirect_count=0,
            sha256=obj.sha256,
            byte_size=obj.byte_size,
            pinned_ip="1.2.3.4",
            observed_at=observed_at,
            peer_ip="1.2.3.4",
            trace=trace,
        )
        return result, obj
