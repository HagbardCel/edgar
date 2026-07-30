"""Locked test: offline worker replays strictly from manifest + object store.

Builds a tiny two-document DTS (schema + label linkbase), stores bytes in an
object store, serializes uri-bindings-v1, stages a sterile manifest, and runs
the offline-manifest worker job with network denied. No network, no database.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.manifest import build_sterile_manifest  # noqa: E402
from spike_lib.storage import ObjectStore, write_json_atomic  # noqa: E402
from spike_lib.uri_bindings import (  # noqa: E402
    URI_BINDINGS_LOGICAL_PATH,
    UriBinding,
    serialize_bindings,
)
from spike_lib.uri_identity import normalize_uri  # noqa: E402
from spike_lib.worker import run_offline_manifest_job  # noqa: E402

EX_XSD_URI = "https://example.com/taxonomy/ex.xsd"
EX_LAB_URI = "https://example.com/taxonomy/ex-lab.xml"

EX_XSD = """<?xml version="1.0" encoding="UTF-8"?>
<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    targetNamespace="http://example.com/ex"
    xmlns:ex="http://example.com/ex"
    xmlns:link="http://www.xbrl.org/2003/linkbase"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    elementFormDefault="qualified">
  <xsd:annotation>
    <xsd:appinfo>
      <link:linkbaseRef xlink:type="simple" xlink:href="ex-lab.xml"
          xlink:role="http://www.w3.org/1999/xlink/properties/linkbase"
          xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
    </xsd:appinfo>
  </xsd:annotation>
  <xsd:element name="Assets" type="xsd:string"/>
</xsd:schema>
"""

EX_LAB = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
    xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
    <link:loc xlink:type="locator" xlink:label="conceptAssets"
        xlink:href="ex.xsd#ex_Assets"/>
    <link:label xlink:type="resource" xlink:label="labelAssets"
        xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en">Assets</link:label>
    <link:labelArc xlink:type="arc"
        xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label"
        xlink:from="conceptAssets" xlink:to="labelAssets" order="1"/>
  </link:labelLink>
</link:linkbase>
"""


def _artifact(logical_path: str, sha: str, size: int, role: str) -> SimpleNamespace:
    return SimpleNamespace(
        logical_path=logical_path,
        sha256=sha,
        byte_size=size,
        source_url=None,
        source_class="generated",
        artifact_role=role,
        sec_sequence=None,
        sec_document_type=None,
        sec_description=None,
        required=True,
        in_payload=True,
    )


def test_offline_worker_loads_strictly_from_manifest(tmp_path: Path) -> None:
    accession_root = tmp_path / "acc"
    store = ObjectStore(accession_root)

    xsd_bytes = EX_XSD.encode("utf-8")
    lab_bytes = EX_LAB.encode("utf-8")
    xsd_obj = store.put_bytes(xsd_bytes)
    lab_obj = store.put_bytes(lab_bytes)

    bindings = [
        UriBinding(
            document_uri=normalize_uri(EX_XSD_URI),
            logical_path="dts/ex.xsd",
            content_sha256=xsd_obj.sha256,
        ),
        UriBinding(
            document_uri=normalize_uri(EX_LAB_URI),
            logical_path="dts/ex-lab.xml",
            content_sha256=lab_obj.sha256,
        ),
    ]
    bindings_bytes = serialize_bindings(bindings)
    bindings_obj = store.put_bytes(bindings_bytes)

    artifacts = [
        _artifact("dts/ex.xsd", xsd_obj.sha256, xsd_obj.byte_size, "extension_schema"),
        _artifact("dts/ex-lab.xml", lab_obj.sha256, lab_obj.byte_size, "linkbase"),
        _artifact(
            URI_BINDINGS_LOGICAL_PATH,
            bindings_obj.sha256,
            bindings_obj.byte_size,
            "uri_bindings",
        ),
    ]
    draft = SimpleNamespace(
        cik="0001065088",
        accession="0001065088-24-000036",
        artifacts=artifacts,
        artifact_by_path=lambda path: next((a for a in artifacts if a.logical_path == path), None),
    )
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=normalize_uri(EX_XSD_URI))
    manifest_path = tmp_path / "manifest.json"
    write_json_atomic(manifest_path, manifest)

    result_path = tmp_path / "result.json"
    job = {
        "mode": "offline-manifest",
        "manifest_path": str(manifest_path),
        "object_store_root": str(accession_root),
        "expected_manifest_sha256": __import__("hashlib")
        .sha256(manifest_path.read_bytes())
        .hexdigest(),
        "cache_dir": str(tmp_path / "cache"),
        "work_dir": str(tmp_path / "work"),
        "result_path": str(result_path),
        "log_path": str(tmp_path / "offline.log"),
        "user_agent": None,
    }
    payload = run_offline_manifest_job(job)
    assert "error" not in payload, payload.get("issues")
    snapshot = payload["snapshot"]

    doc_uris = {d["canonical_uri"] for d in snapshot["documents"]}
    assert doc_uris == {normalize_uri(EX_XSD_URI), normalize_uri(EX_LAB_URI)}
    by_uri = {d["canonical_uri"]: d for d in snapshot["documents"]}
    assert by_uri[normalize_uri(EX_XSD_URI)]["content_sha256"] == xsd_obj.sha256
    assert by_uri[normalize_uri(EX_LAB_URI)]["content_sha256"] == lab_obj.sha256

    edge_pairs = {
        (e["source_uri"], e["discovery_type"], e["target_uri"]) for e in snapshot["edges"]
    }
    assert (
        normalize_uri(EX_XSD_URI),
        "linkbase_ref",
        normalize_uri(EX_LAB_URI),
    ) in edge_pairs

    assert snapshot["unresolved_uris"] == []
    assert payload["network_attempts"] == []
    assert payload["offline_cache_was_empty"] is True
    config = snapshot["engine_config"]
    assert config["work_offline"] is True
    assert config["deny_network"] is True
    assert config["offline_cache_populated_from_manifest"] is True


def test_offline_worker_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    job = {
        "mode": "offline-manifest",
        "manifest_path": str(manifest_path),
        "object_store_root": str(tmp_path / "acc"),
        "expected_manifest_sha256": "00" * 32,
        "cache_dir": str(tmp_path / "cache"),
        "work_dir": str(tmp_path / "work"),
        "result_path": str(result_path),
        "log_path": None,
        "user_agent": None,
    }
    payload = run_offline_manifest_job(job)
    assert payload.get("error") == "MANIFEST_HASH_MISMATCH"
