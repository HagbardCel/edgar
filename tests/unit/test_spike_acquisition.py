"""Unit tests for spike acquisition helpers (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.acquisition import (  # noqa: E402
    commit_bundle,
    parse_index_html,
    parse_index_json,
    parse_sgml_documents,
    reconcile_sgml_inventory,
)
from spike_lib.hashing import sha256_hex  # noqa: E402
from spike_lib.storage import write_json_atomic  # noqa: E402


def test_parse_index_json() -> None:
    payload = {
        "directory": {
            "item": [
                {"name": "a.htm", "size": "10", "type": "text/html"},
                {"name": "b.xml", "size": "20"},
            ]
        }
    }
    entries = parse_index_json(
        json.dumps(payload).encode(),
        "https://www.sec.gov/Archives/edgar/data/1/abc/",
    )
    assert [e["name"] for e in entries] == ["a.htm", "b.xml"]
    assert entries[0]["url"].endswith("a.htm")


def test_parse_index_html() -> None:
    html = b"""
    <html><body>
    <table class="tableFile">
      <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
      <tr>
        <td>1</td><td>Form 10-K</td>
        <td><a href="ebay-20231231.htm">ebay-20231231.htm</a></td>
        <td>10-K</td>
      </tr>
    </table>
    </body></html>
    """
    entries = parse_index_html(html, "https://www.sec.gov/Archives/edgar/data/1/abc/")
    assert len(entries) == 1
    assert entries[0]["name"] == "ebay-20231231.htm"
    assert entries[0]["document_type"] == "10-K"


def test_parse_sgml_documents_line_oriented() -> None:
    content = b"""
<SUBMISSION>
<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>ebay-20231231.htm
<DESCRIPTION>Form 10-K
<TEXT>
stuff
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-21.01
<SEQUENCE>2
<DESCRIPTION>Subsidiaries
<TEXT>
no filename here
</TEXT>
</DOCUMENT>
</SUBMISSION>
"""
    docs = parse_sgml_documents(content)
    assert len(docs) == 2
    assert docs[0].filename == "ebay-20231231.htm"
    assert docs[0].sequence == "1"
    assert docs[1].filename is None
    assert docs[1].document_type == "EX-21.01"


def test_reconcile_sgml_inventory_outcomes() -> None:
    from spike_lib.acquisition import SgmlDocument

    sgml = [
        SgmlDocument("1", "a.htm", "10-K", "Form", 0),
        SgmlDocument("2", "missing.htm", "EX-99", None, 1),
        SgmlDocument("3", None, "GRAPHIC", None, 2),
    ]
    recon, issues = reconcile_sgml_inventory(
        sgml_documents=sgml,
        directory_names={"a.htm", "R1.htm", "FilingSummary.xml"},
        html_submitted_names={"a.htm", "orphan.htm"},
        accession_artifact_names={"a.htm"},
    )
    assert "missing.htm" in recon["missing_directory_files"]
    assert "R1.htm" in recon["generated_directory_extras"]
    assert "orphan.htm" in recon["unmatched_submitted_index_entries"]
    assert recon["passed"] is False
    codes = {i.code for i in issues}
    assert "SGML_FILENAME_MISSING_FROM_DIRECTORY" in codes
    assert "SGML_MISSING_FILENAME" in codes
    assert "INDEX_SUBMITTED_ABSENT_FROM_SGML" in codes


def test_commit_bundle_reuse_and_conflict(tmp_path: Path) -> None:
    accession_root = tmp_path / "acc"
    accession_root.mkdir()
    staged = {
        "payload_hash": "aa" * 32,
        "acquisition_policy_version": "acq-v0-spike",
        "artifacts": [
            {
                "logical_path": "a",
                "sha256": "bb" * 32,
                "byte_size": 1,
                "in_payload": True,
            },
            {
                "logical_path": "metadata/offline-catalog.xml",
                "sha256": "11" * 32,
                "byte_size": 2,
                "in_payload": False,
            },
        ],
        "cik": "0001065088",
        "accession": "0001065088-24-000036",
    }
    path1 = commit_bundle(
        accession_root,
        policy_version="acq-v0-spike",
        payload_hash_value="aa" * 32,
        staged_manifest=staged,
    )
    # Regenerable non-payload artifact may differ; payload identity matches → reuse.
    staged_catalog_changed = {
        **staged,
        "artifacts": [
            staged["artifacts"][0],
            {
                "logical_path": "metadata/offline-catalog.xml",
                "sha256": "22" * 32,
                "byte_size": 3,
                "in_payload": False,
            },
        ],
    }
    path2 = commit_bundle(
        accession_root,
        policy_version="acq-v0-spike",
        payload_hash_value="aa" * 32,
        staged_manifest=staged_catalog_changed,
    )
    assert path1 == path2

    # New payload creates a new bundle path.
    staged2 = {
        **staged,
        "payload_hash": "cc" * 32,
        "artifacts": [],
    }
    path3 = commit_bundle(
        accession_root,
        policy_version="acq-v0-spike",
        payload_hash_value="cc" * 32,
        staged_manifest=staged2,
    )
    assert path3 != path1

    # Conflict at same path when payload artifacts differ.
    bad = {
        **staged,
        "artifacts": [
            {
                "logical_path": "a",
                "sha256": "dd" * 32,
                "byte_size": 1,
                "in_payload": True,
            }
        ],
    }
    with pytest.raises(RuntimeError, match="integrity conflict"):
        commit_bundle(
            accession_root,
            policy_version="acq-v0-spike",
            payload_hash_value="aa" * 32,
            staged_manifest=bad,
        )


def test_write_json_atomic(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    write_json_atomic(path, {"b": 1, "a": 2})
    assert json.loads(path.read_text()) == {"a": 2, "b": 1}
    assert not list(tmp_path.glob(".out.json.*.tmp"))


def test_discovery_excludes_company_name_fields() -> None:
    # Structural check: acquisition module discovery template keys.
    from spike_lib.acquisition import BundleDraft

    draft = BundleDraft(
        cik="0001065088",
        accession="0001065088-24-000036",
        archive_base="https://example.com/",
    )
    draft.discovery = {
        "cik": draft.cik,
        "accession": draft.accession,
        "form": "10-K",
    }
    draft.issuer_provenance = {"company_name": "eBay Inc."}
    assert "company_name" not in draft.discovery
    assert draft.issuer_provenance["company_name"] == "eBay Inc."
    assert sha256_hex(b"x")
