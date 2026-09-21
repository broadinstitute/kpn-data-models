#!/usr/bin/env python3
"""Step 1: Parse and consolidate all source data files.

Reads:
  - raw/Phenotypes.tsv (master phenotype registry)
  - raw/portal_to_mesh_curated_collected.tsv (curated MeSH mappings)
  - raw/amp-traits-mapping-portal-phenotypes_06262024.csv (AMP EFO mappings)
  - raw/gcat_v1.0.3.1.tsv (GWAS Catalog for gcat_trait EFO/MONDO mappings)
  - raw/Phenotypes.tsv rare_v2 rows (embedded Orphanet IDs)

Writes:
  - data/01_consolidated_phenotypes.json

Dependencies: pandas
"""
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
RAW = ROOT / "raw" / "phenotype"
OUT = ROOT / "data" / "phenotype"
OUT.mkdir(exist_ok=True, parents=True)


# ──────────────────────────────────────────────────────────
# Legacy display_group → standardized trait_group mapping
# Consolidates 55 legacy groups into ~30 biological categories
# ──────────────────────────────────────────────────────────
DISPLAY_GROUP_TO_TRAIT_GROUP = {
    # Cardiovascular cluster
    "CARDIOVASCULAR": "cardiovascular",
    "ECG_TRAITS": "cardiovascular",
    "ATRIAL_FIBRILLATION": "cardiovascular",
    "STROKE": "cardiovascular",
    "VASCULAR": "cardiovascular",
    "CEREBROVASCULAR_MRI_TRAITS": "cardiovascular",
    "HERMES_PHENOTYPES": "cardiovascular",
    # Metabolic cluster
    "METABOLIC": "metabolic",
    "GLYCEMIC": "metabolic",
    "DIABETIC_COMPLICATIONS": "metabolic",
    "TYPE_1_DIABETES": "metabolic",
    # Skin cluster
    "DERMATOLOGICAL": "dermatological",
    "SKIN_CONDITIONS": "dermatological",
    "SKIN_KNOWLEDGE_PORTAL": "dermatological",
    # Eye cluster
    "OCULAR": "ocular",
    "VISION_GENOMICS": "ocular",
    # Lipids cluster
    "LIPIDS": "lipids",
    "IGVF_LIPIDS": "lipids",
    # Anthropometric cluster
    "ANTHROPOMETRIC": "anthropometric",
    "GIANT_PHENOTYPES": "anthropometric",
    "PHYSICAL_ACTIVITY": "anthropometric",
    # ENT cluster
    "HEARING": "ent",
    "OTOLARYNGOLOGICAL": "ent",
    # Sleep cluster
    "SLEEP_AND_CIRCADIAN": "sleep",
    "PRIVATE_SLEEP_PORTAL": "sleep",
    # Digestive cluster
    "DIGESTIVE": "digestive",
    "INFLAMMATORY_BOWEL": "digestive",
    # Infectious cluster
    "INFECTIOUS": "infectious",
    "COVID-19": "infectious",
    # Neurological cluster
    "NEUROLOGICAL": "neurological",
    "COGNITIVE": "neurological",
    # Developmental/congenital cluster
    "DEVELOPMENTAL": "congenital",
    "GENETIC": "congenital",
    "NEPHBCH": "congenital",
    # Pharmacogenomics cluster
    "PHARMACOGENOMICS": "pharmacogenomics",
    "SULFONYLUREA_RESPONSE": "pharmacogenomics",
    "METFORMIN_RESPONSE": "pharmacogenomics",
    # Respiratory (rename from LUNG)
    "LUNG": "respiratory",
    # Direct mappings (1:1)
    "AGING_AND_LONGEVITY": "aging",
    "CANCER": "cancer",
    "DENTAL": "dental",
    "ENDOCRINE": "endocrine",
    "ENVIRONMENTAL_EXPOSURE": "environmental",
    "HEMATOLOGICAL": "hematological",
    "HEPATIC": "hepatic",
    "IMMUNOLOGICAL": "immunological",
    "METABOLITE": "metabolite",
    "MUSCULOSKELETAL": "musculoskeletal",
    "NUTRITIONAL": "nutritional",
    "PROTEIN_BIOLOGY": "protein_biology",
    "PSYCHIATRIC": "psychiatric",
    "RENAL": "renal",
    "REPRODUCTIVE_TRAITS": "reproductive",
    # Catch-all
    "NON-ADDITIVE_MODELS": "other",
    "OTHER": "other",
}


def map_trait_group(display_group: str) -> str:
    """Map a legacy display_group to a standardized trait_group."""
    return DISPLAY_GROUP_TO_TRAIT_GROUP.get(display_group, "other")


# ──────────────────────────────────────────────────────────
# 1. Parse Phenotypes.tsv
# ──────────────────────────────────────────────────────────
def parse_phenotypes(path: Path) -> list[dict]:
    """Parse the master phenotype registry."""
    df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    records = []
    for _, row in df.iterrows():
        records.append(
            {
                "gwas_source_category": "KPN" if row["trait_group"] == "portal" else row["trait_group"],
                "phenotype": row["phenotype"],
                "phenotype_name": row["phenotype_name"],
                "legacy_trait_group": row["display_group"],
            }
        )
    print(f"  Phenotypes.tsv: {len(records)} rows")
    return records


# ──────────────────────────────────────────────────────────
# 2. Classify trait type from naming patterns + AMP metadata
# ──────────────────────────────────────────────────────────
# Pre-compiled patterns for trait type classification
_INTERACTION_X = re.compile(r"x[A-Z]")  # e.g., AFxBMI
_INTERACTION_SUFFIX = re.compile(r"(int|joint|main)$")  # e.g., SmokingT2Dint
_STRATIFIED_IN = re.compile(r"In[A-Z]|in[A-Z]|InT2D|inT2D")  # e.g., AlbInT2D
_STRATIFIED_V = re.compile(r"v[A-Z].*_")  # e.g., AllDKDvControl_DM
_ADJUSTED = re.compile(r"adj|Adj")  # e.g., ISIadjAgeSexBMI
_COMPOSITE_OR = re.compile(r"_or_")  # e.g., AD_or_AD_history
_TIME_SUFFIX = re.compile(r"\d+(yr|yrs|mons|mo|wk|wks|day|days)$")  # e.g., BMI1yr
_AGE_SUFFIX = re.compile(r"AGE[oy]\d+")  # e.g., AFxAGEo65
_ORPHANET_ID = re.compile(r"Orphanet_(\d+)")
_MEASUREMENT_SUFFIX = re.compile(r"_measurement$")
_DISEASE_SUFFIX = re.compile(
    r"(_disease|_syndrome|_disorder|_deficiency|_cancer|_carcinoma|"
    r"_lymphoma|_melanoma|_leukemia|_sarcoma)$",
    re.IGNORECASE,
)


def classify_trait_type(
    phenotype: str,
    trait_group: str,
    phenotype_name: str,
    amp_info: dict | None = None,
) -> str:
    """Classify a phenotype into a trait type based on naming heuristics."""
    # rare_v2 → rare_disease
    if trait_group == "rare_v2":
        return "rare_disease"

    # Check interaction patterns (must come before stratified since some overlap)
    if _INTERACTION_X.search(phenotype):
        # Distinguish subgroup (age/sex stratified) from true interactions
        if _AGE_SUFFIX.search(phenotype):
            return "subgroup"
        return "interaction"
    if _INTERACTION_SUFFIX.search(phenotype):
        return "interaction"

    # Adjusted
    if _ADJUSTED.search(phenotype):
        return "adjusted"

    # Stratified
    if _STRATIFIED_IN.search(phenotype):
        return "stratified"
    if _STRATIFIED_V.search(phenotype):
        return "stratified"

    # Composite
    if _COMPOSITE_OR.search(phenotype):
        return "composite"

    # Time-specific subgroup
    if _TIME_SUFFIX.search(phenotype):
        return "subgroup"

    # gcat_trait heuristics based on name
    if trait_group == "gcat_trait":
        name_lower = phenotype_name.lower()
        if _MEASUREMENT_SUFFIX.search(phenotype):
            return "measurement"
        # Check for measurement-like keywords
        if any(
            kw in name_lower
            for kw in [
                "level",
                "concentration",
                "ratio",
                "index",
                "count",
                "volume",
                "rate",
                "percentage",
                "density",
                "thickness",
                "length",
                "width",
                "height",
                "weight",
                "mass",
                "area",
                "pressure",
                "velocity",
                "flow",
                "response to",
            ]
        ):
            return "measurement"
        if _DISEASE_SUFFIX.search(phenotype):
            return "disease"
        if any(
            kw in name_lower
            for kw in [
                "disease",
                "syndrome",
                "disorder",
                "cancer",
                "carcinoma",
                "lymphoma",
                "melanoma",
                "leukemia",
                "sarcoma",
                "deficiency",
                "infection",
                "allergy",
            ]
        ):
            return "disease"
        # Default for gcat_trait: phenotype (general observable characteristic)
        return "phenotype"

    # portal phenotypes — use AMP metadata if available
    if amp_info:
        complex_trait = amp_info.get("complex traits", "")
        dichotomous = amp_info.get("dichotomous", "")
        if complex_trait == "simple":
            if dichotomous == "1":
                return "disease"
            elif dichotomous == "0":
                return "measurement"

    # Fallback heuristics for portal phenotypes based on name
    name_lower = phenotype_name.lower()
    if any(
        kw in name_lower
        for kw in [
            "disease",
            "syndrome",
            "disorder",
            "cancer",
            "carcinoma",
        ]
    ):
        return "disease"

    # Default
    return "phenotype"


# ──────────────────────────────────────────────────────────
# 3. Parse MeSH mappings
# ──────────────────────────────────────────────────────────
def parse_mesh_mappings(path: Path) -> dict[str, list[str]]:
    """Parse portal_to_mesh_curated_collected.tsv → {portal_id: [mesh_ids]}."""
    df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    mapping = defaultdict(list)
    for _, row in df.iterrows():
        pid = row["portal_id"].strip()
        mid = row["mesh_id"].strip()
        if pid and mid and mid.lower() != "none":
            if mid not in mapping[pid]:
                mapping[pid].append(mid)
    print(f"  MeSH mappings: {len(mapping)} phenotypes, {sum(len(v) for v in mapping.values())} pairs")
    return dict(mapping)


# ──────────────────────────────────────────────────────────
# 4. Parse AMP/EFO mappings
# ──────────────────────────────────────────────────────────
RELATION_TO_SKOS = {
    "Exact match": "skos:exactMatch",
    "exact match": "skos:exactMatch",
    "Match to parent": "skos:broadMatch",
    "match to parent": "skos:broadMatch",
    "need import": None,
    "Need to be imported": None,
    "need to be imported": None,
    "No mapping needed": None,
    "Already in EFO": "skos:exactMatch",
    "already in EFO": "skos:exactMatch",
}


def parse_amp_mappings(path: Path) -> dict[str, dict]:
    """Parse AMP EFO mapping CSV → {name: {efo_id, relation, complex_traits, dichotomous, ...}}."""
    records = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip()
            if not name:
                continue
            efo_id_raw = row.get("EFO_id", "").strip()
            relation_raw = row.get("Relation", "").strip()
            # Normalize EFO ID: EFO_0000275 → EFO:0000275, CHEBI_28875 → CHEBI:28875
            efo_id = ""
            if efo_id_raw:
                efo_id = re.sub(r"^(EFO|CHEBI|CMO|OBA|MONDO|HP|DOID)_", r"\1:", efo_id_raw)

            skos_predicate = RELATION_TO_SKOS.get(relation_raw)
            # Also try case-insensitive match
            if skos_predicate is None and relation_raw:
                skos_predicate = RELATION_TO_SKOS.get(relation_raw.lower())

            records[name] = {
                "efo_id": efo_id,
                "relation_raw": relation_raw,
                "skos_predicate": skos_predicate,
                "complex_traits": row.get("complex traits", "").strip(),
                "dichotomous": row.get("dichotomous", "").strip(),
                "description": row.get("description", "").strip(),
                "comments": row.get("comments", "").strip(),
                "lizzy_suggestion": row.get("Lizzy's suggestion", "").strip(),
                "maria_suggestion": row.get("Maria's suggestion", "").strip(),
            }
    print(f"  AMP mappings: {len(records)} phenotypes")
    return records


# ──────────────────────────────────────────────────────────
# 5. Parse GWAS Catalog for gcat_trait mappings
# ──────────────────────────────────────────────────────────
def parse_gwas_catalog(path: Path) -> dict[str, list[dict]]:
    """Parse GWAS Catalog → {disease_trait_lower: [{mapped_trait, mapped_trait_uri}]}.

    We build a lookup from DISEASE/TRAIT (lowercased) to the MAPPED_TRAIT_URI(s).
    """
    mapping = defaultdict(list)
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            disease_trait = row.get("DISEASE/TRAIT", "").strip()
            mapped_trait = row.get("MAPPED_TRAIT", "").strip()
            mapped_uri = row.get("MAPPED_TRAIT_URI", "").strip()
            if not disease_trait or not mapped_uri:
                continue
            key = disease_trait.lower()
            # Avoid duplicate entries
            entry = {"mapped_trait": mapped_trait, "mapped_trait_uri": mapped_uri}
            if entry not in mapping[key]:
                mapping[key].append(entry)
    print(f"  GWAS Catalog: {len(mapping)} unique traits with mappings")
    return dict(mapping)


def uri_to_curie(uri: str) -> str:
    """Convert an ontology URI to a CURIE.

    e.g., http://www.ebi.ac.uk/efo/EFO_0000275 → EFO:0000275
          http://purl.obolibrary.org/obo/MONDO_0004981 → MONDO:0004981
    """
    prefix_map = {
        "http://www.ebi.ac.uk/efo/EFO_": "EFO:",
        "http://purl.obolibrary.org/obo/MONDO_": "MONDO:",
        "http://purl.obolibrary.org/obo/HP_": "HP:",
        "http://purl.obolibrary.org/obo/DOID_": "DOID:",
        "http://purl.obolibrary.org/obo/CHEBI_": "CHEBI:",
        "http://purl.obolibrary.org/obo/OBA_": "OBA:",
        "http://purl.obolibrary.org/obo/CMO_": "CMO:",
        "http://www.orpha.net/ORDO/Orphanet_": "ORPHANET:",
        "http://id.nlm.nih.gov/mesh/": "MESH:",
        # Newer EFO pattern
        "http://www.ebi.ac.uk/efo/": "EFO:",
        # OBO generic
        "http://purl.obolibrary.org/obo/": "",
    }
    for prefix, curie_prefix in prefix_map.items():
        if uri.startswith(prefix):
            local = uri[len(prefix):]
            if not curie_prefix and "_" in local:
                # Generic OBO: GO_0001234 → GO:0001234
                parts = local.split("_", 1)
                return f"{parts[0]}:{parts[1]}"
            return f"{curie_prefix}{local}"
    return uri  # Return as-is if no match


def ontology_from_curie(curie: str) -> str:
    """Extract ontology name from CURIE."""
    mapping = {
        "EFO": "EFO",
        "MONDO": "MONDO",
        "HP": "HP",
        "DOID": "DOID",
        "CHEBI": "CHEBI",
        "OBA": "OBA",
        "CMO": "CMO",
        "Orphanet": "ORPHANET",
        "ORPHANET": "ORPHANET",
        "MESH": "MESH",
        "MeSH": "MESH",
    }
    prefix = curie.split(":")[0] if ":" in curie else ""
    return mapping.get(prefix, prefix)


# ──────────────────────────────────────────────────────────
# 6. Extract Orphanet IDs from rare_v2 phenotype names
# ──────────────────────────────────────────────────────────
def extract_orphanet_id(phenotype: str) -> str | None:
    """Extract Orphanet ID from rare_v2 phenotype string."""
    m = _ORPHANET_ID.search(phenotype)
    if m:
        return f"ORPHANET:{m.group(1)}"
    return None


# ──────────────────────────────────────────────────────────
# 7. Parse ORDO labels for PIGEAN missing phenotypes
# ──────────────────────────────────────────────────────────
_OWL_CLASS = "{http://www.w3.org/2002/07/owl#}Class"
_RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
_RDFS_LABEL = "{http://www.w3.org/2000/01/rdf-schema#}label"
_ORPHANET_IRI_PREFIX = "http://www.orpha.net/ORDO/Orphanet_"


def build_ordo_label_map(ordo_path: Path) -> dict[str, str]:
    """Extract Orphanet ID → disease name from ORDO OWL via streaming XML parse.

    Uses iterparse for memory efficiency (~43MB file parses in seconds).
    """
    labels: dict[str, str] = {}
    if not ordo_path.exists():
        print(f"  WARNING: {ordo_path} not found, ORDO labels unavailable")
        return labels

    print(f"  Parsing ORDO labels from {ordo_path.name}...")
    for event, elem in ET.iterparse(str(ordo_path), events=("end",)):
        if elem.tag == _OWL_CLASS:
            about = elem.get(_RDF_ABOUT, "")
            if about.startswith(_ORPHANET_IRI_PREFIX):
                orphanet_num = about[len(_ORPHANET_IRI_PREFIX) :]
                label_elem = elem.find(_RDFS_LABEL)
                if label_elem is not None and label_elem.text:
                    labels[orphanet_num] = label_elem.text.strip()
            elem.clear()
    print(f"  Extracted {len(labels)} Orphanet labels from ORDO")
    return labels


# ──────────────────────────────────────────────────────────
# 8. Helpers for PIGEAN missing phenotypes
# ──────────────────────────────────────────────────────────
_CAMEL_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def camel_case_to_name(s: str) -> str:
    """Split camelCase or PascalCase string into space-separated words.

    Examples: 'SerumUrea' → 'Serum Urea', 'Testosterone' → 'Testosterone'
    """
    return _CAMEL_SPLIT.sub(" ", s)


def name_to_phenotype_id(name: str, orphanet_num: str) -> str:
    """Convert a disease name to a legacy phenotype ID.

    Matches existing rare_v2 convention: spaces→underscores, remove hyphens/slashes/commas/parens.
    e.g., 'Hermansky-Pudlak syndrome' + '79430' → 'HermanskyPudlak_syndrome_Orphanet_79430'
    """
    clean = name.replace("-", "").replace("/", "").replace(",", "")
    clean = clean.replace("(", "").replace(")", "").replace("'", "")
    clean = clean.replace(" ", "_")
    # Collapse multiple underscores
    clean = re.sub(r"_+", "_", clean).strip("_")
    return f"{clean}_Orphanet_{orphanet_num}"


def parse_pigean_missing(
    path: Path,
    ordo_labels: dict[str, str],
    gwas_catalog: dict[str, list[dict]],
    amp_mappings: dict[str, dict],
    mesh_mappings: dict[str, list[str]],
) -> list[dict]:
    """Parse PIGEAN missing phenotypes file and create consolidated records.

    Handles three categories:
      - rare_v2_Orphanet_NNNNN → rare disease with ORDO name lookup
      - gcat_trait_* → GWAS Catalog trait
      - everything else → KPN phenotype
    """
    if not path.exists():
        print(f"  WARNING: {path} not found, skipping PIGEAN phenotypes")
        return []

    with open(path) as f:
        raw_ids = [line.strip() for line in f if line.strip()]

    print(f"  PIGEAN missing phenotypes file: {len(raw_ids)} entries")

    records: list[dict] = []
    stats = {"rare_v2": 0, "gcat_trait": 0, "KPN": 0, "names_resolved": 0}

    for raw_id in raw_ids:
        if raw_id.startswith("rare_v2_Orphanet_"):
            orphanet_num = raw_id[len("rare_v2_Orphanet_") :]
            disease_name = ordo_labels.get(orphanet_num, "")

            if disease_name:
                stats["names_resolved"] += 1
                phenotype_id = name_to_phenotype_id(disease_name, orphanet_num)
                phenotype_name = disease_name
            else:
                # Fallback: use raw ID format
                phenotype_id = raw_id
                phenotype_name = f"Orphanet {orphanet_num}"

            records.append(
                {
                    "gwas_source_category": "rare_v2",
                    "phenotype": phenotype_id,
                    "phenotype_name": phenotype_name,
                    "legacy_trait_group": "OTHER",
                    "trait_group": "other",
                    "trait_type": "rare_disease",
                    "pigean_id": raw_id,
                    "mappings": [
                        {
                            "target_id": f"ORPHANET:{orphanet_num}",
                            "target_ontology": "ORPHANET",
                            "target_label": disease_name,
                            "mapping_predicate": "skos:exactMatch",
                            "confidence": 0.95,
                            "mapping_justification": "lexical_match",
                            "source": "PIGEAN phenotype (embedded Orphanet ID)",
                        }
                    ],
                }
            )
            stats["rare_v2"] += 1

        elif raw_id.startswith("gcat_trait_"):
            name = raw_id[len("gcat_trait_") :].replace("_", " ")
            trait_type = classify_trait_type(raw_id, "gcat_trait", name)

            # Try to get GWAS Catalog mappings
            mappings: list[dict] = []
            gwas_entries = gwas_catalog.get(name.lower(), [])
            for entry in gwas_entries:
                uris = entry["mapped_trait_uri"]
                labels = entry["mapped_trait"]
                uri_list = [u.strip() for u in uris.split(",") if u.strip()]
                label_list = [l.strip() for l in labels.split(",")]
                for i, uri in enumerate(uri_list):
                    curie = uri_to_curie(uri)
                    ontology = ontology_from_curie(curie)
                    label = label_list[i] if i < len(label_list) else ""
                    existing_ids = {m["target_id"] for m in mappings}
                    if curie not in existing_ids:
                        mappings.append(
                            {
                                "target_id": curie,
                                "target_label": label,
                                "target_ontology": ontology,
                                "mapping_predicate": "skos:exactMatch",
                                "confidence": 0.9,
                                "mapping_justification": "gwas_catalog",
                                "source": "gcat_v1.0.3.1.tsv",
                            }
                        )

            records.append(
                {
                    "gwas_source_category": "gcat_trait",
                    "phenotype": raw_id,
                    "phenotype_name": name,
                    "legacy_trait_group": "OTHER",
                    "trait_group": "other",
                    "trait_type": trait_type,
                    "pigean_id": raw_id,
                    "mappings": mappings,
                }
            )
            stats["gcat_trait"] += 1

        else:
            # KPN phenotype (e.g., SerumUrea, Testosterone)
            name = camel_case_to_name(raw_id)
            amp_info = amp_mappings.get(raw_id)
            trait_type = classify_trait_type(raw_id, "KPN", name, amp_info)

            mappings = []
            if amp_info and amp_info["efo_id"] and amp_info["skos_predicate"]:
                efo_id = amp_info["efo_id"]
                ontology = ontology_from_curie(efo_id)
                mappings.append(
                    {
                        "target_id": efo_id,
                        "target_ontology": ontology,
                        "mapping_predicate": amp_info["skos_predicate"],
                        "confidence": 0.85,
                        "mapping_justification": "inherited",
                        "source": "amp-traits-mapping-portal-phenotypes_06262024.csv",
                    }
                )

            # Check MeSH mappings too
            mesh_ids = mesh_mappings.get(raw_id, [])
            for mid in mesh_ids:
                mappings.append(
                    {
                        "target_id": f"MESH:{mid}",
                        "target_ontology": "MESH",
                        "mapping_predicate": "skos:exactMatch",
                        "confidence": 0.85,
                        "mapping_justification": "inherited",
                        "source": "portal_to_mesh_curated_collected.tsv",
                    }
                )

            records.append(
                {
                    "gwas_source_category": "KPN",
                    "phenotype": raw_id,
                    "phenotype_name": name,
                    "legacy_trait_group": "OTHER",
                    "trait_group": "other",
                    "trait_type": trait_type,
                    "pigean_id": raw_id,
                    "mappings": mappings,
                }
            )
            if amp_info:
                records[-1]["amp_description"] = amp_info.get("description", "")
                records[-1]["amp_complex"] = amp_info.get("complex_traits", "")
                records[-1]["amp_dichotomous"] = amp_info.get("dichotomous", "")
            stats["KPN"] += 1

    print(f"    rare_v2:    {stats['rare_v2']} ({stats['names_resolved']} names resolved from ORDO)")
    print(f"    gcat_trait: {stats['gcat_trait']}")
    print(f"    KPN:        {stats['KPN']}")

    return records


# ──────────────────────────────────────────────────────────
# Main consolidation
# ──────────────────────────────────────────────────────────
def main():
    print("Step 1: Parsing and consolidating source data\n")

    # 1. Parse all sources
    print("Parsing source files...")
    phenotypes = parse_phenotypes(RAW / "Phenotypes.tsv")
    mesh_mappings = parse_mesh_mappings(RAW / "portal_to_mesh_curated_collected.tsv")
    amp_mappings = parse_amp_mappings(
        RAW / "amp-traits-mapping-portal-phenotypes_06262024.csv"
    )
    gwas_catalog = parse_gwas_catalog(RAW / "gcat_v1.0.3.1.tsv")

    # 1b. Parse PIGEAN missing phenotypes
    print("\nParsing PIGEAN missing phenotypes...")
    ordo_labels = build_ordo_label_map(RAW / "ORDO_en_4.5.owl")
    pigean_path = RAW / "phenoypes_not_in_phenotype_list_but_where_in_pigean_runs.txt"
    pigean_records = parse_pigean_missing(
        pigean_path, ordo_labels, gwas_catalog, amp_mappings, mesh_mappings,
    )

    # 2. Build consolidated records
    print("\nConsolidating records...")
    consolidated = []
    # Track stats
    stats = {
        "total": 0,
        "by_group": defaultdict(int),
        "by_type": defaultdict(int),
        "with_mesh": 0,
        "with_efo": 0,
        "with_orphanet": 0,
        "with_gwas_efo": 0,
        "with_any_mapping": 0,
    }

    for pheno in phenotypes:
        stats["total"] += 1
        stats["by_group"][pheno["gwas_source_category"]] += 1

        phenotype_id = pheno["phenotype"]
        trait_group = pheno["gwas_source_category"]
        phenotype_name = pheno["phenotype_name"]
        display_group = pheno["legacy_trait_group"]

        # Get AMP info if available
        amp_info = amp_mappings.get(phenotype_id)

        # Classify trait type
        trait_type = classify_trait_type(
            phenotype_id, trait_group, phenotype_name, amp_info
        )
        stats["by_type"][trait_type] += 1

        # Build mappings list
        mappings = []

        # MeSH mappings
        mesh_ids = mesh_mappings.get(phenotype_id, [])
        for mid in mesh_ids:
            mappings.append(
                {
                    "target_id": f"MESH:{mid}",
                    "target_ontology": "MESH",
                    "mapping_predicate": "skos:exactMatch",
                    "confidence": 0.85,
                    "mapping_justification": "inherited",
                    "source": "portal_to_mesh_curated_collected.tsv",
                }
            )

        # AMP/EFO mappings
        if amp_info and amp_info["efo_id"] and amp_info["skos_predicate"]:
            efo_id = amp_info["efo_id"]
            ontology = ontology_from_curie(efo_id)
            mappings.append(
                {
                    "target_id": efo_id,
                    "target_ontology": ontology,
                    "mapping_predicate": amp_info["skos_predicate"],
                    "confidence": 0.85,
                    "mapping_justification": "inherited",
                    "source": "amp-traits-mapping-portal-phenotypes_06262024.csv",
                    "notes": amp_info.get("comments", ""),
                }
            )

        # GWAS Catalog mappings for gcat_trait
        if trait_group == "gcat_trait":
            # Match by phenotype_name (lowercased) to DISEASE/TRAIT
            gwas_entries = gwas_catalog.get(phenotype_name.lower(), [])
            for entry in gwas_entries:
                uris = entry["mapped_trait_uri"]
                labels = entry["mapped_trait"]
                # Can be comma-separated
                uri_list = [u.strip() for u in uris.split(",") if u.strip()]
                label_list = [l.strip() for l in labels.split(",")]
                for i, uri in enumerate(uri_list):
                    curie = uri_to_curie(uri)
                    ontology = ontology_from_curie(curie)
                    label = label_list[i] if i < len(label_list) else ""
                    # Skip if we already have this mapping
                    existing_ids = {m["target_id"] for m in mappings}
                    if curie not in existing_ids:
                        mappings.append(
                            {
                                "target_id": curie,
                                "target_label": label,
                                "target_ontology": ontology,
                                "mapping_predicate": "skos:exactMatch",
                                "confidence": 0.9,
                                "mapping_justification": "gwas_catalog",
                                "source": "gcat_v1.0.3.1.tsv",
                            }
                        )

        # Orphanet IDs for rare_v2
        if trait_group == "rare_v2":
            orphanet_id = extract_orphanet_id(phenotype_id)
            if orphanet_id:
                mappings.append(
                    {
                        "target_id": orphanet_id,
                        "target_ontology": "ORPHANET",
                        "mapping_predicate": "skos:exactMatch",
                        "confidence": 0.95,
                        "mapping_justification": "lexical_match",
                        "source": "Phenotypes.tsv (embedded Orphanet ID)",
                    }
                )

        # Update stats
        has_mesh = any(m["target_ontology"] == "MESH" for m in mappings)
        has_efo = any(m["target_ontology"] == "EFO" for m in mappings)
        has_orphanet = any(m["target_ontology"] == "ORPHANET" for m in mappings)
        has_gwas = any(m["mapping_justification"] == "gwas_catalog" for m in mappings)
        if has_mesh:
            stats["with_mesh"] += 1
        if has_efo:
            stats["with_efo"] += 1
        if has_orphanet:
            stats["with_orphanet"] += 1
        if has_gwas:
            stats["with_gwas_efo"] += 1
        if mappings:
            stats["with_any_mapping"] += 1

        # Build record
        record = {
            "gwas_source_category": trait_group,
            "phenotype": phenotype_id,
            "phenotype_name": phenotype_name,
            "legacy_trait_group": display_group,
            "trait_group": map_trait_group(display_group),
            "trait_type": trait_type,
            "mappings": mappings,
        }

        # Add AMP metadata if available
        if amp_info:
            record["amp_description"] = amp_info.get("description", "")
            record["amp_complex"] = amp_info.get("complex_traits", "")
            record["amp_dichotomous"] = amp_info.get("dichotomous", "")

        consolidated.append(record)

    # 2b. Append PIGEAN records and update stats
    consolidated.extend(pigean_records)
    for record in pigean_records:
        stats["total"] += 1
        stats["by_group"][record["gwas_source_category"]] += 1
        stats["by_type"][record["trait_type"]] += 1
        has_mesh = any(m["target_ontology"] == "MESH" for m in record.get("mappings", []))
        has_efo = any(m["target_ontology"] == "EFO" for m in record.get("mappings", []))
        has_orphanet = any(m["target_ontology"] == "ORPHANET" for m in record.get("mappings", []))
        has_gwas = any(m["mapping_justification"] == "gwas_catalog" for m in record.get("mappings", []))
        if has_mesh:
            stats["with_mesh"] += 1
        if has_efo:
            stats["with_efo"] += 1
        if has_orphanet:
            stats["with_orphanet"] += 1
        if has_gwas:
            stats["with_gwas_efo"] += 1
        if record.get("mappings"):
            stats["with_any_mapping"] += 1

    # 3. Write output
    output_path = OUT / "01_consolidated_phenotypes.json"
    with open(output_path, "w") as f:
        json.dump(consolidated, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(consolidated)} records to {output_path}")

    # 4. Print stats
    print("\n" + "=" * 60)
    print("CONSOLIDATION SUMMARY")
    print("=" * 60)
    print(f"Total phenotypes: {stats['total']}")
    print(f"\nBy trait group:")
    for group, count in sorted(stats["by_group"].items()):
        print(f"  {group}: {count}")
    print(f"\nBy trait type:")
    for ttype, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
        print(f"  {ttype}: {count}")
    print(f"\nMapping coverage (from existing sources):")
    print(f"  With MeSH mapping:    {stats['with_mesh']:,} ({stats['with_mesh']/stats['total']*100:.1f}%)")
    print(f"  With EFO mapping:     {stats['with_efo']:,} ({stats['with_efo']/stats['total']*100:.1f}%)")
    print(f"  With Orphanet:        {stats['with_orphanet']:,} ({stats['with_orphanet']/stats['total']*100:.1f}%)")
    print(f"  With GWAS Catalog:    {stats['with_gwas_efo']:,} ({stats['with_gwas_efo']/stats['total']*100:.1f}%)")
    print(f"  With ANY mapping:     {stats['with_any_mapping']:,} ({stats['with_any_mapping']/stats['total']*100:.1f}%)")
    print(f"  With NO mapping:      {stats['total'] - stats['with_any_mapping']:,} ({(stats['total'] - stats['with_any_mapping'])/stats['total']*100:.1f}%)")

    # 5. Write unmapped phenotypes for review
    unmapped = [r for r in consolidated if not r["mappings"]]
    unmapped_path = OUT / "01_unmapped_phenotypes.json"
    with open(unmapped_path, "w") as f:
        json.dump(unmapped, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(unmapped)} unmapped phenotypes to {unmapped_path}")


if __name__ == "__main__":
    main()
