"""Shared helpers for disposable technical spikes.

Spike code has no compatibility guarantees. Evidence and conclusions are retained.
"""

from __future__ import annotations

# Acquisition / bundle contract versions. Bumping any of these changes bundle identity.
ACQUISITION_POLICY_VERSION = "acq-v1-spike"
MANIFEST_SCHEMA_VERSION = "manifest-v2-spike"
PAYLOAD_HASH_SCHEMA_VERSION = "payload-v1"
URI_BINDING_SCHEMA_VERSION = "uri-bindings-v1"
URI_IDENTITY_VERSION = "uri-identity-v1"

# Canonicalization versions for semantic identity records.
RESOURCE_SERIALIZATION_VERSION = "xbrl-resource-v1"
RELATIONSHIP_SERIALIZATION_VERSION = "xbrl-relationship-v1"
SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION = "synthetic-document-v1"
SEMANTIC_RUN_SCHEMA_VERSION = "semantic-run-v1"
ARELLE_ERROR_POLICY_VERSION = "arelle-error-policy-v1"

# Evidence package contract versions.
EVIDENCE_SCHEMA_VERSION = "evidence-v1"
EVIDENCE_EXPORTER_VERSION = "evidence-export-v1"

# Helper generator versions.
CATALOG_GENERATOR_VERSION = "catalog-v0-spike"
DISCOVERY_EXTRACTION_POLICY_VERSION = "discovery-v0-spike"
