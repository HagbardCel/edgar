"""Compare current offline extract to a pinned P0 baseline directory."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from edgar.corpus_acceptance import resolve_published_bundle
from edgar.p0_compare_policy import compare_v6_filter, issue_code_counts, issue_delta
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.semantic import run_offline_extract
from edgar.xbrl.source_wire import report_extraction_to_dict

INVARIANT = frozenset({"contexts", "dimensions", "units", "measures", "facts", "relationships"})
BASELINE_EXTRACTOR = "source-extract-v5"
CURRENT_EXTRACTOR = "source-extract-v6"


def _require_bundle(repo: BundleRepository, cik: str, accession: str):
    resolution = resolve_published_bundle(repo, cik, accession)
    if resolution.error is not None or resolution.bundle is None:
        raise SystemExit(
            f"{accession}: bundle resolution failed: {resolution.error_code}: {resolution.error}"
        )
    return resolution.bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_dir", type=Path)
    args = parser.parse_args()
    root = Path("var").resolve()
    store = ObjectStore(root)
    repo = BundleRepository(root, store)
    corpus = tomllib.loads(Path("fixtures/corpus.toml").read_text(encoding="utf-8"))
    failed = False
    total_issuer_only = 0
    for filing in corpus["filings"]:
        accession = filing["accession"]
        cik = filing["cik"]
        baseline_path = args.baseline_dir / f"{accession}.json"
        if not baseline_path.is_file():
            print(f"missing baseline {baseline_path}", file=sys.stderr)
            failed = True
            continue
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if baseline.get("extractor_version") != BASELINE_EXTRACTOR:
            print(
                f"{accession}: baseline extractor_version "
                f"{baseline.get('extractor_version')!r} != {BASELINE_EXTRACTOR!r}",
                file=sys.stderr,
            )
            failed = True
        bundle = _require_bundle(repo, cik, accession)
        result = run_offline_extract(bundle, store)
        current = report_extraction_to_dict(result.report)
        if current.get("extractor_version") != CURRENT_EXTRACTOR:
            print(
                f"{accession}: current extractor_version "
                f"{current.get('extractor_version')!r} != {CURRENT_EXTRACTOR!r}",
                file=sys.stderr,
            )
            failed = True
        for name in INVARIANT:
            if current[name] != baseline[name]:
                print(f"{accession}: invariant {name} changed", file=sys.stderr)
                failed = True
        baseline_issues = issue_code_counts(baseline.get("issues", []))
        current_issues = issue_code_counts(current.get("issues", []))
        added, removed = issue_delta(baseline_issues, current_issues)
        if added:
            print(
                f"{accession}: added issue-code occurrences {dict(sorted(added.items()))}",
                file=sys.stderr,
            )
            failed = True
        if removed:
            print(f"{accession}: removed issue-code occurrences {dict(sorted(removed.items()))}")
        filter_result = compare_v6_filter(baseline, current)
        total_issuer_only += filter_result.issuer_only
        print(
            f"{accession}: issuer declarations checked={filter_result.issuer_declarations} "
            f"issuer-only declarations checked={filter_result.issuer_only}"
        )
        for message in filter_result.errors:
            print(f"{accession}: {message}", file=sys.stderr)
            failed = True
        print(
            f"{accession}: concepts {len(baseline['concepts'])} -> {len(current['concepts'])} "
            f"declarations {len(baseline['declarations'])} -> {len(current['declarations'])} "
            f"labels {len(baseline['labels'])} -> {len(current['labels'])} "
            f"references {len(baseline['references'])} -> {len(current['references'])}"
        )
    if total_issuer_only <= 0:
        print(
            "corpus: issuer-only declaration count must be > 0 across six filings",
            file=sys.stderr,
        )
        failed = True
    else:
        print(f"corpus: issuer-only declarations checked total={total_issuer_only}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
