"""Process and filesystem isolation for Arelle loads (ADR 0009).

The worker runs Arelle against a private XDG config home, a freshly created and
initially empty web cache, and a closed-world workspace. Local bytes are bound
to their canonical HTTP(S) document URI through Arelle's own web-cache layout,
so ``ModelDocument.uri`` (and therefore every relative reference base) stays the
canonical URI even though nothing is downloaded.

Arelle objects must not escape this module and :mod:`edgar.xbrl.worker`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from edgar.domain.identifiers import validate_logical_path
from edgar.storage.objects import write_bytes_atomic

CATALOG_GENERATOR_VERSION = "oasis-catalog-v1"

PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "FTP_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "ftp_proxy",
    "all_proxy",
)
XML_CATALOG_ENV_VAR = "XML_CATALOG_FILES"
XDG_CONFIG_HOME_ENV_VAR = "XDG_CONFIG_HOME"


class WebCacheLike(Protocol):
    """Structural view of the Arelle ``WebCache`` methods this module needs."""

    def urlToCacheFilepath(self, url: str) -> str: ...

    def normalizeFilepath(self, filepath: str, url: str) -> str: ...


def is_http_uri(uri: str) -> bool:
    return urlsplit(uri).scheme in ("http", "https")


@dataclass(frozen=True)
class IsolatedArelleEnv:
    """Temporary directory set backing one isolated Arelle process."""

    root: Path
    config_home: Path
    cache_dir: Path
    workspace: Path
    catalog_path: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def create_isolated_env(
    *,
    parent: Path | None = None,
    prefix: str = "edgar-arelle-",
) -> IsolatedArelleEnv:
    """Create an empty, private config/cache/workspace triple."""
    root = Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent) if parent else None))
    config_home = root / "config"
    cache_dir = root / "cache"
    workspace = root / "workspace"
    catalog_dir = root / "catalog"
    for directory in (config_home, cache_dir, workspace, catalog_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return IsolatedArelleEnv(
        root=root,
        config_home=config_home,
        cache_dir=cache_dir,
        workspace=workspace,
        catalog_path=catalog_dir / "oasis-catalog.xml",
    )


def clear_proxy_environment() -> dict[str, str]:
    """Remove proxy variables from the process environment; return removals."""
    removed: dict[str, str] = {}
    for key in PROXY_ENV_VARS:
        value = os.environ.pop(key, None)
        if value is not None:
            removed[key] = value
    return removed


def clear_xml_catalog_environment() -> str | None:
    """Remove an ambient ``XML_CATALOG_FILES``; return the prior value."""
    return os.environ.pop(XML_CATALOG_ENV_VAR, None)


@contextmanager
def isolated_process_environment(
    env: IsolatedArelleEnv,
    *,
    catalog_path: Path | None = None,
) -> Iterator[None]:
    """Apply isolation to ``os.environ`` for the duration of the block."""
    prior_config_home = os.environ.get(XDG_CONFIG_HOME_ENV_VAR)
    prior_catalog = clear_xml_catalog_environment()
    prior_proxies = clear_proxy_environment()
    os.environ[XDG_CONFIG_HOME_ENV_VAR] = str(env.config_home)
    if catalog_path is not None:
        os.environ[XML_CATALOG_ENV_VAR] = str(catalog_path.resolve())
    try:
        yield
    finally:
        if prior_config_home is None:
            os.environ.pop(XDG_CONFIG_HOME_ENV_VAR, None)
        else:
            os.environ[XDG_CONFIG_HOME_ENV_VAR] = prior_config_home
        os.environ.pop(XML_CATALOG_ENV_VAR, None)
        if prior_catalog is not None:
            os.environ[XML_CATALOG_ENV_VAR] = prior_catalog
        os.environ.update(prior_proxies)


def materialize_workspace(
    documents: Mapping[str, tuple[str, bytes]],
    workspace: Path,
) -> dict[str, Path]:
    """Write ``document_uri -> (relative_path, content)`` into ``workspace``.

    Returns the canonical ``document_uri -> local path`` map used to build the
    catalog and to seed the Arelle web cache.
    """
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, Path] = {}
    for uri in sorted(documents):
        relative_path, content = documents[uri]
        validate_logical_path(relative_path)
        target = (workspace / relative_path).resolve()
        if not target.is_relative_to(workspace):
            raise ValueError(f"workspace path escapes root: {relative_path!r}")
        write_bytes_atomic(target, content)
        mapping[uri] = target
    return mapping


def build_oasis_catalog(uri_to_path: Mapping[str, Path], catalog_path: Path) -> bytes:
    """Write an OASIS catalog mapping canonical URIs to catalog-relative paths."""
    catalog_path = catalog_path.resolve()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- generator={CATALOG_GENERATOR_VERSION} -->",
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
    ]
    for uri in sorted(uri_to_path):
        target = uri_to_path[uri].resolve()
        try:
            relative = Path(os.path.relpath(target, start=catalog_path.parent)).as_posix()
        except ValueError:
            relative = target.as_uri()
        name = escape(uri, {'"': "&quot;"})
        value = escape(relative, {'"': "&quot;"})
        lines.append(f'  <uri name="{name}" uri="{value}"/>')
    lines.append("</catalog>")
    lines.append("")
    data = "\n".join(lines).encode("utf-8")
    write_bytes_atomic(catalog_path, data)
    return data


def web_cache_filepath(web_cache: WebCacheLike, uri: str) -> Path:
    """Arelle cache filepath for ``uri`` under the controller's cache dir."""
    raw = web_cache.urlToCacheFilepath(uri)
    return Path(web_cache.normalizeFilepath(raw, uri))


def write_web_cache_document(web_cache: WebCacheLike, uri: str, content: bytes) -> Path:
    """Place ``content`` where Arelle expects the cached bytes for ``uri``."""
    if not is_http_uri(uri):
        raise ValueError(f"web cache materialization requires an http(s) URI: {uri!r}")
    target = web_cache_filepath(web_cache, uri)
    write_bytes_atomic(target, content)
    return target


def materialize_web_cache(
    web_cache: WebCacheLike,
    uri_to_path: Mapping[str, Path],
) -> dict[str, Path]:
    """Seed an empty Arelle web cache from local bytes keyed by canonical URI."""
    written: dict[str, Path] = {}
    for uri in sorted(uri_to_path):
        source = uri_to_path[uri]
        if not is_http_uri(uri) or not source.is_file():
            continue
        written[uri] = write_web_cache_document(web_cache, uri, source.read_bytes())
    return written


def create_isolated_controller(
    *,
    cache_dir: Path,
    work_offline: bool,
    user_agent: str | None = None,
    plugins: Sequence[str] = (),
) -> Any:
    """Create an Arelle ``Cntlr`` with no persistent config and a private cache.

    The returned object is an Arelle controller; callers must keep it inside the
    adapter boundary.
    """
    from arelle import Cntlr, PluginManager

    cache_dir.mkdir(parents=True, exist_ok=True)
    cntlr = Cntlr.Cntlr(logFileName="logToBuffer", disable_persistent_config=True)
    cntlr.webCache.cacheDir = str(cache_dir)
    cntlr.webCache.workOffline = work_offline
    if user_agent:
        cntlr.webCache.httpUserAgent = user_agent
    if plugins:
        for name in plugins:
            PluginManager.addPluginModule(name)
        PluginManager.reset()
    return cntlr


def arelle_version() -> str:
    import arelle.Version

    return str(
        getattr(arelle.Version, "__version__", None)
        or getattr(arelle.Version, "version", None)
        or "unknown"
    )
