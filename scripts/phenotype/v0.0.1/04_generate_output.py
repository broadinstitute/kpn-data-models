#!/usr/bin/env python3
"""Step 4: Assign stable KPN.TRAIT IDs and generate versioned output files.

Reads:
  - data/phenotype/03_ols_enriched_mappings.json

Writes (into data/phenotype/v{VERSION}/):
  - kpn_trait_registry.tsv — the ID registry
  - kpn_trait_mappings.sssom.tsv — SSSOM mapping set
  - kpn_trait_collection.yaml — LinkML instance data

The base version generated from source files is always v0.0.1.
Subsequent manual curation versions increment from there.

Usage:
  python 04_generate_output.py              # generates v0.0.1
  python 04_generate_output.py --version 0.0.2  # generates v0.0.2

Dependencies: pyyaml
"""
import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA = ROOT / "data" / "phenotype"
TRAIT_BASE_URL = "https://broadinstitute.github.io/kpn-data-models/kpn.trait/"

JUSTIFICATION_TO_SEMAPV = {
    "manual_curation": "semapv:ManualMappingCuration",
    "lexical_match": "semapv:LexicalMatching",
    "cross_reference": "semapv:MappingByLogicalReasoning",
    "semantic_similarity": "semapv:SemanticSimilarityThresholdMatching",
    "gwas_catalog": "semapv:MappingByLogicalReasoning",
    "inherited": "semapv:ManualMappingCuration",
}


def load_input(input_path: Path | None = None) -> list[dict]:
    """Load enriched data."""
    if input_path:
        print(f"  Loading from {input_path}")
        with open(input_path) as f:
            return json.load(f)

    default = DATA / "03_ols_enriched_mappings.json"
    if default.exists():
        print(f"  Loading from {default}")
        with open(default) as f:
            return json.load(f)

    print("ERROR: No input data found. Run Steps 1-3 first.")
    sys.exit(1)


def load_release(release_dir: Path) -> list[dict]:
    """Rebuild without re-querying ontologies; retain YAML mapping provenance.

    The flat export carries the original dichotomous/complex flags, which are
    not both represented in the LinkML collection.
    """
    with (release_dir / "kpn_trait_collection.yaml").open() as f:
        phenotypes = yaml.safe_load(f)["phenotypes"]
    with (release_dir / "kpn_trait_flat.tsv").open(newline="") as f:
        flags = {}
        for row in csv.DictReader(f, delimiter="\t"):
            flags.setdefault(row["portal_id"], row)
    records = []
    for phenotype in phenotypes:
        row = flags[phenotype["portal_id"]]
        records.append({
            **phenotype,
            "phenotype": phenotype["legacy_id"],
            "amp_description": phenotype.get("description", ""),
            "amp_dichotomous": row["is_dichotomous"],
            "amp_complex": {"true": "complex", "false": "simple"}.get(row["is_complex"], ""),
        })
    return records


def assign_portal_ids(records: list[dict], registry_path: Path | None = None) -> list[dict]:
    """Reuse assigned numbers, allocating new IDs above the registry maximum.

    Names and classifications may change without changing identity. Missing
    registry records fail closed so rebuilding cannot silently drop traits.
    The legacy source category "portal" is an alias of "KPN" in both inputs
    and registries, so the source rename never allocates a new identity.
    """
    for record in records:
        if record["gwas_source_category"] == "portal":
            record["gwas_source_category"] = "KPN"
    assigned = {}
    used = set()
    if registry_path is not None:
        with registry_path.open(newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                source = row["gwas_source_category"]
                key = ("KPN" if source == "portal" else source, row["legacy_phenotype_id"])
                match = re.fullmatch(r"(?:PORTAL|KPN\.TRAIT):([0-9]{7})", row["portal_id"])
                if not match or int(match[1]) == 0:
                    raise ValueError(f"Invalid registry ID: {row['portal_id']}")
                number = int(match[1])
                if key in assigned or number in used:
                    raise ValueError(f"Duplicate registry identity or ID: {key}")
                assigned[key] = number
                used.add(number)
    keys = [(r["gwas_source_category"], r["phenotype"]) for r in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate phenotype identity in input")
    missing = assigned.keys() - set(keys)
    if missing:
        raise ValueError(f"Input drops {len(missing)} registered phenotypes: {sorted(missing)[:3]}")
    group_order = {"KPN": 0, "gcat_trait": 1, "rare_v2": 2}
    records.sort(
        key=lambda r: (
            group_order.get(r["gwas_source_category"], 9),
            r.get("legacy_trait_group", ""),
            r.get("phenotype", ""),
        )
    )
    next_id = max(used, default=0) + 1
    for record in records:
        key = (record["gwas_source_category"], record["phenotype"])
        if key not in assigned:
            if next_id > 9999999:
                raise ValueError("KPN.TRAIT ID space exhausted")
            assigned[key] = next_id
            next_id += 1
        record["portal_id"] = f"KPN.TRAIT:{assigned[key]:07d}"
    records.sort(key=lambda r: r["portal_id"])
    return records


def select_primary_mapping(mappings: list[dict]) -> dict | None:
    if not mappings:
        return None
    ontology_priority = {"EFO": 0, "MONDO": 1, "MESH": 2, "HP": 3, "DOID": 4, "ORPHANET": 5}
    predicate_priority = {
        "skos:exactMatch": 0,
        "skos:closeMatch": 1,
        "skos:broadMatch": 2,
        "skos:narrowMatch": 3,
        "skos:relatedMatch": 4,
    }

    def score(m):
        return (
            predicate_priority.get(m.get("mapping_predicate", ""), 9),
            -m.get("confidence", 0),
            ontology_priority.get(m.get("target_ontology", ""), 9),
        )

    return min(mappings, key=score)


def generate_registry(records: list[dict], output_path: Path):
    fieldnames = [
        "portal_id", "gwas_source_category", "legacy_phenotype_id",
        "phenotype_name", "legacy_trait_group", "trait_group", "trait_type",
        "pigean_id",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for r in records:
            writer.writerow({
                "portal_id": r["portal_id"],
                "gwas_source_category": r["gwas_source_category"],
                "legacy_phenotype_id": r["phenotype"],
                "phenotype_name": r["phenotype_name"],
                "legacy_trait_group": r.get("legacy_trait_group", ""),
                "trait_group": r.get("trait_group", "other"),
                "trait_type": r["trait_type"],
                "pigean_id": r.get("pigean_id", ""),
            })
    print(f"  Wrote registry: {output_path} ({len(records)} entries)")


def generate_sssom(records: list[dict], output_path: Path, version: str, mapping_date: str | None = None):
    today = mapping_date or date.today().isoformat()
    header_lines = [
        "# curie_map:",
        f"#   KPN.TRAIT: {TRAIT_BASE_URL}",
        "#   EFO: http://www.ebi.ac.uk/efo/EFO_",
        "#   MESH: http://id.nlm.nih.gov/mesh/",
        "#   MONDO: http://purl.obolibrary.org/obo/MONDO_",
        "#   HP: http://purl.obolibrary.org/obo/HP_",
        "#   DOID: http://purl.obolibrary.org/obo/DOID_",
        "#   ORPHANET: http://www.orpha.net/ORDO/Orphanet_",
        "#   CHEBI: http://purl.obolibrary.org/obo/CHEBI_",
        "#   OBA: http://purl.obolibrary.org/obo/OBA_",
        "#   CMO: http://purl.obolibrary.org/obo/CMO_",
        "#   ICD10CM: http://purl.bioontology.org/ontology/ICD10CM/",
        "#   OMIM: https://omim.org/entry/",
        "#   GO: http://purl.obolibrary.org/obo/GO_",
        "#   NCIT: http://purl.obolibrary.org/obo/NCIT_",
        "#   PATO: http://purl.obolibrary.org/obo/PATO_",
        "#   skos: http://www.w3.org/2004/02/skos/core#",
        "#   semapv: https://w3id.org/semapv/vocab/",
        "#   oboInOwl: http://www.geneontology.org/formats/oboInOwl#",
        f"# mapping_set_id: {TRAIT_BASE_URL}mappings",
        f"# mapping_set_version: v{version} ({today})",
    ]
    fieldnames = [
        "subject_id", "subject_label", "predicate_id",
        "object_id", "object_label", "mapping_justification", "confidence",
    ]

    total = 0
    with open(output_path, "w", newline="") as f:
        for line in header_lines:
            f.write(line + "\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for r in records:
            for m in r.get("mappings", []):
                semapv = JUSTIFICATION_TO_SEMAPV.get(
                    m.get("mapping_justification", ""), "semapv:UnspecifiedMatching"
                )
                writer.writerow({
                    "subject_id": r["portal_id"],
                    "subject_label": r["phenotype_name"],
                    "predicate_id": m.get("mapping_predicate", ""),
                    "object_id": m.get("target_id", ""),
                    "object_label": m.get("target_label", ""),
                    "mapping_justification": semapv,
                    "confidence": m.get("confidence", ""),
                })
                total += 1
    print(f"  Wrote SSSOM: {output_path} ({total} mappings)")


def generate_linkml_instances(records: list[dict], output_path: Path):
    phenotypes = []
    for r in records:
        primary = select_primary_mapping(r.get("mappings", []))
        pheno = {
            "portal_id": r["portal_id"],
            "legacy_id": r["phenotype"],
            "gwas_source_category": r["gwas_source_category"],
            "phenotype_name": r["phenotype_name"],
            "legacy_trait_group": r.get("legacy_trait_group", ""),
            "trait_group": r.get("trait_group", "other"),
            "trait_type": r["trait_type"],
        }
        if r.get("pigean_id"):
            pheno["pigean_id"] = r["pigean_id"]
        if r.get("amp_description"):
            pheno["description"] = r["amp_description"]
        if r.get("amp_dichotomous"):
            pheno["is_dichotomous"] = r["amp_dichotomous"] == "1"
        if primary:
            pheno["primary_mapping"] = {
                "target_id": primary["target_id"],
                "target_label": primary.get("target_label", ""),
                "target_ontology": primary["target_ontology"],
                "mapping_predicate": primary["mapping_predicate"],
                "mapping_justification": primary.get("mapping_justification", ""),
                "confidence": primary.get("confidence"),
            }
        if r.get("mappings"):
            pheno["mappings"] = []
            for m in r["mappings"]:
                entry = {
                    "target_id": m["target_id"],
                    "target_ontology": m["target_ontology"],
                    "mapping_predicate": m["mapping_predicate"],
                    "mapping_justification": m.get("mapping_justification", ""),
                    "confidence": m.get("confidence"),
                }
                if m.get("target_label"):
                    entry["target_label"] = m["target_label"]
                if m.get("source"):
                    entry["source"] = m["source"]
                if m.get("notes"):
                    entry["notes"] = m["notes"]
                pheno["mappings"].append(entry)
        phenotypes.append(pheno)

    with open(output_path, "w") as f:
        yaml.dump(
            {"phenotypes": phenotypes}, f,
            default_flow_style=False, allow_unicode=True, sort_keys=False, width=120,
        )
    print(f"  Wrote LinkML instances: {output_path} ({len(phenotypes)} phenotypes)")


def generate_flattened_tsv(records: list[dict], output_path: Path):
    """Generate a flattened TSV with one row per mapping, all phenotype fields repeated."""
    fieldnames = [
        "portal_id", "gwas_source_category", "legacy_trait_group", "trait_group",
        "phenotype", "phenotype_name", "description", "trait_type",
        "is_dichotomous", "is_complex", "pigean_id", "mapping_count",
        "target_id", "target_label", "target_ontology",
        "mapping_predicate", "confidence", "mapping_justification", "source",
    ]

    total = 0
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()

        for r in records:
            mappings = r.get("mappings", [])
            pheno_fields = {
                "portal_id": r["portal_id"],
                "gwas_source_category": r["gwas_source_category"],
                "legacy_trait_group": r.get("legacy_trait_group", ""),
                "trait_group": r.get("trait_group", "other"),
                "phenotype": r["phenotype"],
                "phenotype_name": r["phenotype_name"],
                "description": r.get("amp_description", ""),
                "trait_type": r["trait_type"],
                "is_dichotomous": r.get("amp_dichotomous", ""),
                "is_complex": "true" if r.get("amp_complex") == "complex" else ("false" if r.get("amp_complex") == "simple" else ""),
                "pigean_id": r.get("pigean_id", ""),
                "mapping_count": len(mappings),
            }

            if not mappings:
                total += 1
                writer.writerow({**pheno_fields, "target_id": "", "target_label": "",
                    "target_ontology": "", "mapping_predicate": "", "confidence": "",
                    "mapping_justification": "", "source": ""})
            else:
                for m in mappings:
                    total += 1
                    writer.writerow({
                        **pheno_fields,
                        "target_id": m.get("target_id", ""),
                        "target_label": m.get("target_label", ""),
                        "target_ontology": m.get("target_ontology", ""),
                        "mapping_predicate": m.get("mapping_predicate", ""),
                        "confidence": m.get("confidence", ""),
                        "mapping_justification": m.get("mapping_justification", ""),
                        "source": m.get("source", ""),
                    })

    print(f"  Wrote flattened TSV: {output_path} ({total} rows)")


def main():
    parser = argparse.ArgumentParser(description="Generate versioned portal phenotype output")
    parser.add_argument("--version", default="0.0.1", help="Version string (default: 0.0.1)")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input", type=Path, help="Enriched input JSON")
    inputs.add_argument("--from-release", type=Path, help="Rebuild an existing release offline (YAML + flat TSV)")
    parser.add_argument("--registry", type=Path, help="Existing registry to preserve (defaults to output registry, then v0.0.1)")
    parser.add_argument("--output-dir", type=Path, help="Optional output directory")
    parser.add_argument("--mapping-date", help="SSSOM date, YYYY-MM-DD; defaults to source release date on rebuild")
    args = parser.parse_args()

    version = args.version
    VERSIONS = ROOT / "versions" / "phenotype"
    version_dir = args.output_dir or VERSIONS / f"v{version}"
    version_dir.mkdir(exist_ok=True, parents=True)

    print(f"Generating v{version} output\n")

    records = load_release(args.from_release) if args.from_release else load_input(args.input)
    print(f"  {len(records)} phenotype records\n")

    registry = args.registry
    if registry is None:
        candidates = [
            (args.from_release or version_dir) / "kpn_trait_registry.tsv",
            VERSIONS / "v0.0.1" / "kpn_trait_registry.tsv",
        ]
        registry = next((path for path in candidates if path.exists()), None)
    mapping_date = args.mapping_date
    if args.from_release and mapping_date is None:
        metadata = (args.from_release / "kpn_trait_mappings.sssom.tsv").read_text()
        match = re.search(r"^# mapping_set_version: .*\((\d{4}-\d{2}-\d{2})\)$", metadata, re.M)
        if not match:
            raise ValueError("Source release has no mapping date; pass --mapping-date")
        mapping_date = match[1]
    if mapping_date:
        date.fromisoformat(mapping_date)
    print("Assigning KPN.TRAIT IDs...")
    records = assign_portal_ids(records, registry)
    print(f"  {records[0]['portal_id']} to {records[-1]['portal_id']}\n")

    print("Generating output files...")
    generate_registry(records, version_dir / "kpn_trait_registry.tsv")
    generate_sssom(records, version_dir / "kpn_trait_mappings.sssom.tsv", version, mapping_date)
    generate_linkml_instances(records, version_dir / "kpn_trait_collection.yaml")
    generate_flattened_tsv(records, version_dir / "kpn_trait_flat.tsv")

    print(f"\nOutput: {version_dir}/")
    print(f"\nTo validate:")
    print(f"  linkml-validate -s schemas/phenotype/portal_phenotype.yaml {version_dir}/kpn_trait_collection.yaml")


if __name__ == "__main__":
    main()
