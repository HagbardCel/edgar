"""edgar.xbrl package."""

from edgar.xbrl.arelle_env import (
    IsolatedArelleEnv,
    build_oasis_catalog,
    create_isolated_env,
    materialize_web_cache,
    materialize_workspace,
)
from edgar.xbrl.closure import (
    ClosureDiscovery,
    ExternalDocument,
    LoadedDocument,
    ResolvedDocument,
    WorkerProtocolError,
    external_artifact_path,
    run_online_closure,
    run_worker_process,
)
from edgar.xbrl.network_guard import (
    NetworkAttempt,
    NetworkDeniedError,
    NetworkGuard,
    deny_inet_sockets,
)
from edgar.xbrl.replay import ReplayValidationResult, validate_offline_replay
from edgar.xbrl.uri import (
    URI_IDENTITY_VERSION,
    UriIdentityError,
    assert_serialized_binding_uri,
    normalize_uri,
    resolve_document_uri,
    sha256_of_uri,
)

__all__ = [
    "URI_IDENTITY_VERSION",
    "ClosureDiscovery",
    "ExternalDocument",
    "IsolatedArelleEnv",
    "LoadedDocument",
    "NetworkAttempt",
    "NetworkDeniedError",
    "NetworkGuard",
    "ReplayValidationResult",
    "ResolvedDocument",
    "UriIdentityError",
    "WorkerProtocolError",
    "assert_serialized_binding_uri",
    "build_oasis_catalog",
    "create_isolated_env",
    "deny_inet_sockets",
    "external_artifact_path",
    "materialize_web_cache",
    "materialize_workspace",
    "normalize_uri",
    "resolve_document_uri",
    "run_online_closure",
    "run_worker_process",
    "sha256_of_uri",
    "validate_offline_replay",
]
