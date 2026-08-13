"""Unit tests for bundle_fingerprint portability."""

from __future__ import annotations

from pathlib import Path

from edgar.domain.bundle import bundle_fingerprint, bundles_equivalent
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from tests.helpers.xbrl_bundles import make_minimal_semantic_bundle


def test_bundle_fingerprint_equal_for_equivalent_bundles(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    left = make_minimal_semantic_bundle(ObjectStore(root_a))
    right = make_minimal_semantic_bundle(ObjectStore(root_b))
    assert bundles_equivalent(left, right)
    assert bundle_fingerprint(left) == bundle_fingerprint(right)


def test_republish_assigns_different_opaque_ids_same_fingerprint(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    store_a = ObjectStore(root_a)
    store_b = ObjectStore(root_b)
    bundle = make_minimal_semantic_bundle(store_a)
    for artifact in bundle.artifacts:
        digest = artifact.content.sha256
        if not store_b.exists(digest):
            store_b.put_bytes(store_a.open_bytes(digest))
    pub_a = BundleRepository(root_a, store_a).publish(bundle)
    pub_b = BundleRepository(root_b, store_b).publish(bundle)
    assert pub_a.opaque_id != pub_b.opaque_id
    loaded_a = BundleRepository(root_a, store_a).load(pub_a.bundle_dir)
    loaded_b = BundleRepository(root_b, store_b).load(pub_b.bundle_dir)
    assert bundle_fingerprint(loaded_a) == bundle_fingerprint(loaded_b)
