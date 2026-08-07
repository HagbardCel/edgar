"""Shared helpers for disposable technical spikes.

Spike code has no compatibility guarantees. Evidence and conclusions are retained.
"""

from __future__ import annotations

# Acquisition / bundle contract versions. Bumping any of these changes bundle identity.
ACQUISITION_POLICY_VERSION = "acq-v2-spike"
MANIFEST_SCHEMA_VERSION = "manifest-v3-spike"
PAYLOAD_HASH_SCHEMA_VERSION = "payload-v1"
URI_BINDING_SCHEMA_VERSION = "uri-bindings-v2"
URI_IDENTITY_VERSION = "uri-identity-v1"

# Canonicalization versions for semantic identity records.
RESOURCE_SERIALIZATION_VERSION = "xbrl-resource-v2"
RELATIONSHIP_SERIALIZATION_VERSION = "xbrl-relationship-v2"
CLOSURE_SERIALIZATION_VERSION = "closure-v1"
SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION = "synthetic-document-v1"
SEMANTIC_RUN_SCHEMA_VERSION = "semantic-run-v2"
ARELLE_ERROR_POLICY_VERSION = "arelle-error-policy-v2"

# Evidence package contract versions.
EVIDENCE_SCHEMA_VERSION = "evidence-v2"
EVIDENCE_EXPORTER_VERSION = "evidence-export-v2"
SAMPLES_POLICY_VERSION = "inspection-samples-v1"

# Helper generator versions.
CATALOG_GENERATOR_VERSION = "catalog-v0-spike"
DISCOVERY_EXTRACTION_POLICY_VERSION = "discovery-v1-spike"
