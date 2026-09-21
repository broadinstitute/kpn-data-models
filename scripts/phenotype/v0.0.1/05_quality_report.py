#!/usr/bin/env python3
"""Step 5: Generate quality/coverage report for a versioned output.

Usage:
  python 05_quality_report.py              # reports on v0.0.1
  python 05_quality_report.py --version 0.0.2

Reads:
  - data/phenotype/v{VERSION}/kpn_trait_registry.tsv
  - data/phenotype/v{VERSION}/kpn_trait_mappings.sssom.tsv

Writes:
  - data/phenotype/v{VERSION}/kpn_trait_coverage.md

Dependencies: pandas
"""
import argparse
from collections import defaultdict
from io import StringIO
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "data" / "phenotype"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.0.1")
    args = parser.parse_args()

    VERSIONS = ROOT / "versions" / "phenotype"
    version_dir = VERSIONS / f"v{args.version}"
    registry_path = version_dir / "kpn_trait_registry.tsv"
    sssom_path = version_dir / "kpn_trait_mappings.sssom.tsv"

    if not registry_path.exists() or not sssom_path.exists():
        print(f"ERROR: v{args.version} output not found at {version_dir}")
        print("Run 04_generate_output.py first.")
        return

    print(f"Generating quality report for v{args.version}\n")

    registry = pd.read_csv(registry_path, sep="\t", dtype=str).fillna("")
    print(f"  Registry: {len(registry)} phenotypes")

    sssom_lines = [line for line in open(sssom_path) if not line.startswith("#")]
    sssom = pd.read_csv(StringIO("".join(sssom_lines)), sep="\t", dtype=str).fillna("")
    print(f"  SSSOM mappings: {len(sssom)} rows")

    sssom["object_ontology"] = sssom["object_id"].apply(
        lambda x: x.split(":")[0] if ":" in x else "unknown"
    )

    portal_ids = set(registry["portal_id"])
    mapped_by_ontology = defaultdict(set)
    mapped_by_predicate = defaultdict(int)

    for _, row in sssom.iterrows():
        mapped_by_ontology[row["object_ontology"]].add(row["subject_id"])
        mapped_by_predicate[row["predicate_id"]] += 1

    group_stats = {}
    for group_name, group_df in registry.groupby("gwas_source_category"):
        group_ids = set(group_df["portal_id"])
        stats = {"total": len(group_ids)}
        for ont in ["EFO", "MESH", "MONDO", "HP", "DOID", "ORPHANET", "CHEBI", "OBA", "CMO", "ICD10CM"]:
            stats[ont] = len(group_ids & mapped_by_ontology.get(ont, set()))
        any_mapped = set()
        for ont_set in mapped_by_ontology.values():
            any_mapped |= (group_ids & ont_set)
        stats["any"] = len(any_mapped)
        stats["none"] = len(group_ids) - len(any_mapped)
        group_stats[group_name] = stats

    type_dist = registry["trait_type"].value_counts().to_dict()

    all_mapped = set()
    for ont_set in mapped_by_ontology.values():
        all_mapped |= ont_set
    unmapped_ids = portal_ids - all_mapped

    # Build report
    lines = [
        f"# Portal Phenotype Mapping Coverage Report — v{args.version}\n",
        "## Overall Summary\n",
        f"- **Total phenotypes**: {len(registry)}",
        f"- **Total mappings**: {len(sssom)}",
        f"- **Phenotypes with any mapping**: {len(all_mapped)} ({len(all_mapped)/len(registry)*100:.1f}%)",
        f"- **Phenotypes with NO mapping**: {len(unmapped_ids)} ({len(unmapped_ids)/len(registry)*100:.1f}%)\n",
        "## Coverage by Ontology\n",
        "| Ontology | Mapped | % of Total |",
        "|----------|--------|------------|",
    ]
    for ont in ["EFO", "MESH", "MONDO", "HP", "DOID", "ORPHANET", "CHEBI", "OBA", "CMO", "ICD10CM"]:
        count = len(mapped_by_ontology.get(ont, set()))
        lines.append(f"| {ont} | {count} | {count/len(registry)*100:.1f}% |")

    lines += [
        "\n## Coverage by Trait Group\n",
        "| Trait Group | Total | EFO | MESH | MONDO | ORPHANET | Any | None |",
        "|-------------|-------|-----|------|-------|----------|-----|------|",
    ]
    for group in ["portal", "gcat_trait", "rare_v2"]:
        s = group_stats.get(group, {})
        t = s.get("total", 1)
        lines.append(
            f"| {group} | {t} | "
            f"{s.get('EFO',0)} ({s.get('EFO',0)/t*100:.0f}%) | "
            f"{s.get('MESH',0)} ({s.get('MESH',0)/t*100:.0f}%) | "
            f"{s.get('MONDO',0)} ({s.get('MONDO',0)/t*100:.0f}%) | "
            f"{s.get('ORPHANET',0)} ({s.get('ORPHANET',0)/t*100:.0f}%) | "
            f"{s.get('any',0)} ({s.get('any',0)/t*100:.0f}%) | "
            f"{s.get('none',0)} ({s.get('none',0)/t*100:.0f}%) |"
        )

    # Quality targets
    portal_s = group_stats.get("portal", {})
    gcat_s = group_stats.get("gcat_trait", {})
    rare_s = group_stats.get("rare_v2", {})
    portal_efo_mondo = len(
        (mapped_by_ontology.get("EFO", set()) | mapped_by_ontology.get("MONDO", set()) | mapped_by_ontology.get("MESH", set()))
        & set(registry[registry["gwas_source_category"] == "portal"]["portal_id"])
    )
    check = lambda actual, target: "PASS" if actual >= target else "FAIL"

    pt = portal_s.get("total", 1)
    gt = gcat_s.get("total", 1)
    rt = rare_s.get("total", 1)
    pct1 = portal_efo_mondo / pt * 100
    pct2 = rare_s.get("ORPHANET", 0) / rt * 100
    pct3 = gcat_s.get("EFO", 0) / gt * 100

    lines += [
        "\n## Quality Targets\n",
        "| Target | Actual | Status |",
        "|--------|--------|--------|",
        f"| >90% portal → EFO/MONDO/MESH | {pct1:.1f}% ({portal_efo_mondo}/{pt}) | {check(pct1, 90)} |",
        f"| >95% rare_v2 → ORPHANET | {pct2:.1f}% ({rare_s.get('ORPHANET',0)}/{rt}) | {check(pct2, 95)} |",
        f"| >80% gcat_trait → EFO | {pct3:.1f}% ({gcat_s.get('EFO',0)}/{gt}) | {check(pct3, 80)} |",
        "\n## Predicate Distribution\n",
        "| Predicate | Count | % |",
        "|-----------|-------|---|",
    ]
    for pred, count in sorted(mapped_by_predicate.items(), key=lambda x: -x[1]):
        lines.append(f"| {pred} | {count} | {count/len(sssom)*100:.1f}% |")

    lines += ["\n## Trait Type Distribution\n", "| Trait Type | Count | % |", "|------------|-------|---|"]
    for ttype, count in sorted(type_dist.items(), key=lambda x: -x[1]):
        lines.append(f"| {ttype} | {count} | {count/len(registry)*100:.1f}% |")

    report_path = version_dir / "kpn_trait_coverage.md"
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    main()
