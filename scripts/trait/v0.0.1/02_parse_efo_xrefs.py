#!/usr/bin/env python3
"""Step 2: Extract cross-references from EFO and ORDO OWL files.

Parses EFO and ORDO ontology files to build a mapping table:
  EFO_ID ↔ {MeSH, MONDO, HP, DOID, Orphanet, ...}
  Orphanet_ID ↔ {MONDO, HP, ...}

Uses rdflib to parse OWL/RDF and extract:
  - hasDbXref annotations
  - exactMatch / closeMatch annotations
  - equivalentClass assertions

Writes:
  - data/trait/02_ontology_xref_table.tsv

Dependencies: rdflib, pandas

NOTE: The EFO OWL file is ~330MB. Parsing will take several minutes.
      The ORDO OWL file is ~45MB.
"""
import csv
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import OWL, RDF, RDFS, SKOS

ROOT = Path(__file__).resolve().parent.parent.parent.parent
RAW = ROOT / "raw" / "trait"
OUT = ROOT / "data" / "trait"
OUT.mkdir(exist_ok=True, parents=True)

# Namespaces
EFO_NS = Namespace("http://www.ebi.ac.uk/efo/")
OBO = Namespace("http://purl.obolibrary.org/obo/")
ORDO = Namespace("http://www.orpha.net/ORDO/")
MESH_NS = Namespace("http://id.nlm.nih.gov/mesh/")
OBOINOWL = Namespace("http://www.geneontology.org/formats/oboInOwl#")

# Properties to look for cross-references
XREF_PROPS = [
    OBOINOWL.hasDbXref,
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.broadMatch,
    SKOS.narrowMatch,
    SKOS.relatedMatch,
]

# Pattern for parsing xref strings like "MONDO:0004981", "MeSH:D001281", "DOID:1826"
CURIE_PATTERN = re.compile(
    r"^(MONDO|MeSH|MESH|DOID|HP|Orphanet|ORDO|CHEBI|OBA|CMO|EFO|OMIM|UMLS|NCIT|SNOMEDCT|ICD10|ICD9):(.+)$"
)

# IRI patterns for detecting ontology source
IRI_PATTERNS = {
    "EFO": re.compile(r"http://www\.ebi\.ac\.uk/efo/EFO_(\d+)"),
    "MONDO": re.compile(r"http://purl\.obolibrary\.org/obo/MONDO_(\d+)"),
    "HP": re.compile(r"http://purl\.obolibrary\.org/obo/HP_(\d+)"),
    "DOID": re.compile(r"http://purl\.obolibrary\.org/obo/DOID_(\d+)"),
    "CHEBI": re.compile(r"http://purl\.obolibrary\.org/obo/CHEBI_(\d+)"),
    "OBA": re.compile(r"http://purl\.obolibrary\.org/obo/OBA_(\d+)"),
    "CMO": re.compile(r"http://purl\.obolibrary\.org/obo/CMO_(\d+)"),
    "ORPHANET": re.compile(r"http://www\.orpha\.net/ORDO/Orphanet_(\d+)"),
}

# Target ontologies we care about for cross-references
TARGET_ONTOLOGIES = {"MONDO", "MESH", "HP", "DOID", "ORPHANET", "CHEBI", "OBA", "CMO", "EFO", "OMIM"}


def iri_to_curie(iri: str) -> str | None:
    """Convert an IRI to a CURIE if it matches a known pattern."""
    for prefix, pattern in IRI_PATTERNS.items():
        m = pattern.match(str(iri))
        if m:
            return f"{prefix}:{m.group(1)}"
    return None


def parse_xref_string(xref: str) -> tuple[str, str] | None:
    """Parse a cross-reference string like 'MONDO:0004981' into (ontology, curie)."""
    m = CURIE_PATTERN.match(xref.strip())
    if m:
        prefix = m.group(1)
        local_id = m.group(2)
        # Normalize prefixes to uppercase
        if prefix == "MeSH":
            prefix = "MESH"
        elif prefix in ("Orphanet", "ORDO"):
            prefix = "ORPHANET"
            # Fix double-prefix: "Orphanet:Orphanet_12345" → just "12345"
            if local_id.startswith("Orphanet_"):
                local_id = local_id[len("Orphanet_"):]
        return (prefix, f"{prefix}:{local_id}")
    return None


def get_label(g: Graph, subject: URIRef) -> str:
    """Get rdfs:label for a subject."""
    for _, _, o in g.triples((subject, RDFS.label, None)):
        return str(o)
    return ""


def parse_efo(path: Path) -> list[dict]:
    """Parse EFO OWL file and extract all cross-references."""
    print(f"  Parsing EFO OWL ({path.stat().st_size / 1e6:.0f} MB)...")
    start = time.time()

    g = Graph()
    g.parse(str(path), format="xml")
    elapsed = time.time() - start
    print(f"  EFO parsed in {elapsed:.0f}s ({len(g)} triples)")

    xrefs = []
    seen = set()

    # Find all OWL classes
    classes = set()
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, URIRef):
            classes.add(s)

    print(f"  Found {len(classes)} OWL classes in EFO")

    for cls in classes:
        source_curie = iri_to_curie(str(cls))
        if not source_curie:
            continue

        source_label = get_label(g, cls)

        # Check all xref properties
        for prop in XREF_PROPS:
            for _, _, obj in g.triples((cls, prop, None)):
                target_curie = None
                predicate = None

                if isinstance(obj, Literal):
                    # String xref like "MONDO:0004981"
                    parsed = parse_xref_string(str(obj))
                    if parsed:
                        ont, target_curie = parsed
                        predicate = "skos:exactMatch"  # hasDbXref implies equivalence
                elif isinstance(obj, URIRef):
                    # IRI xref
                    target_curie = iri_to_curie(str(obj))
                    # Determine predicate from property
                    if prop == SKOS.exactMatch:
                        predicate = "skos:exactMatch"
                    elif prop == SKOS.closeMatch:
                        predicate = "skos:closeMatch"
                    elif prop == SKOS.broadMatch:
                        predicate = "skos:broadMatch"
                    elif prop == SKOS.narrowMatch:
                        predicate = "skos:narrowMatch"
                    elif prop == SKOS.relatedMatch:
                        predicate = "skos:relatedMatch"
                    else:
                        predicate = "skos:exactMatch"

                if target_curie and predicate:
                    target_ont = target_curie.split(":")[0]
                    if target_ont in TARGET_ONTOLOGIES:
                        key = (source_curie, target_curie, predicate)
                        if key not in seen:
                            seen.add(key)
                            xrefs.append(
                                {
                                    "source_id": source_curie,
                                    "source_label": source_label,
                                    "source_ontology": source_curie.split(":")[0],
                                    "target_id": target_curie,
                                    "target_ontology": target_ont,
                                    "mapping_predicate": predicate,
                                    "provenance": "efo.owl",
                                }
                            )

        # Also check equivalentClass for additional xrefs
        for _, _, obj in g.triples((cls, OWL.equivalentClass, None)):
            if isinstance(obj, URIRef):
                target_curie = iri_to_curie(str(obj))
                if target_curie:
                    target_ont = target_curie.split(":")[0]
                    if target_ont in TARGET_ONTOLOGIES:
                        key = (source_curie, target_curie, "skos:exactMatch")
                        if key not in seen:
                            seen.add(key)
                            xrefs.append(
                                {
                                    "source_id": source_curie,
                                    "source_label": source_label,
                                    "source_ontology": source_curie.split(":")[0],
                                    "target_id": target_curie,
                                    "target_ontology": target_ont,
                                    "mapping_predicate": "skos:exactMatch",
                                    "provenance": "efo.owl (equivalentClass)",
                                }
                            )

    print(f"  Extracted {len(xrefs)} cross-references from EFO")
    return xrefs


def parse_ordo(path: Path) -> list[dict]:
    """Parse ORDO OWL file and extract cross-references."""
    print(f"  Parsing ORDO OWL ({path.stat().st_size / 1e6:.0f} MB)...")
    start = time.time()

    g = Graph()
    g.parse(str(path), format="xml")
    elapsed = time.time() - start
    print(f"  ORDO parsed in {elapsed:.0f}s ({len(g)} triples)")

    xrefs = []
    seen = set()

    classes = set()
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, URIRef):
            classes.add(s)

    print(f"  Found {len(classes)} OWL classes in ORDO")

    for cls in classes:
        source_curie = iri_to_curie(str(cls))
        if not source_curie:
            continue

        source_label = get_label(g, cls)

        for prop in XREF_PROPS:
            for _, _, obj in g.triples((cls, prop, None)):
                target_curie = None
                predicate = None

                if isinstance(obj, Literal):
                    parsed = parse_xref_string(str(obj))
                    if parsed:
                        ont, target_curie = parsed
                        predicate = "skos:exactMatch"
                elif isinstance(obj, URIRef):
                    target_curie = iri_to_curie(str(obj))
                    if prop == SKOS.exactMatch:
                        predicate = "skos:exactMatch"
                    elif prop == SKOS.closeMatch:
                        predicate = "skos:closeMatch"
                    else:
                        predicate = "skos:exactMatch"

                if target_curie and predicate:
                    target_ont = target_curie.split(":")[0]
                    if target_ont in TARGET_ONTOLOGIES:
                        key = (source_curie, target_curie, predicate)
                        if key not in seen:
                            seen.add(key)
                            xrefs.append(
                                {
                                    "source_id": source_curie,
                                    "source_label": source_label,
                                    "source_ontology": source_curie.split(":")[0],
                                    "target_id": target_curie,
                                    "target_ontology": target_ont,
                                    "mapping_predicate": predicate,
                                    "provenance": "ORDO_en_4.5.owl",
                                }
                            )

    print(f"  Extracted {len(xrefs)} cross-references from ORDO")
    return xrefs


def main():
    print("Step 2: Extracting cross-references from OWL files\n")

    all_xrefs = []

    # Parse EFO
    efo_path = RAW / "efo.owl"
    if efo_path.exists():
        all_xrefs.extend(parse_efo(efo_path))
    else:
        print(f"  WARNING: {efo_path} not found, skipping EFO")

    # Parse ORDO
    ordo_path = RAW / "ORDO_en_4.5.owl"
    if ordo_path.exists():
        all_xrefs.extend(parse_ordo(ordo_path))
    else:
        print(f"  WARNING: {ordo_path} not found, skipping ORDO")

    # Write TSV
    output_path = OUT / "02_ontology_xref_table.tsv"
    fieldnames = [
        "source_id",
        "source_label",
        "source_ontology",
        "target_id",
        "target_ontology",
        "mapping_predicate",
        "provenance",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(all_xrefs)

    print(f"\nWrote {len(all_xrefs)} cross-references to {output_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("CROSS-REFERENCE SUMMARY")
    print("=" * 60)
    by_source = defaultdict(int)
    by_target = defaultdict(int)
    by_predicate = defaultdict(int)
    for xref in all_xrefs:
        by_source[xref["source_ontology"]] += 1
        by_target[xref["target_ontology"]] += 1
        by_predicate[xref["mapping_predicate"]] += 1

    print("By source ontology:")
    for ont, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {ont}: {count}")

    print("\nBy target ontology:")
    for ont, count in sorted(by_target.items(), key=lambda x: -x[1]):
        print(f"  {ont}: {count}")

    print("\nBy predicate:")
    for pred, count in sorted(by_predicate.items(), key=lambda x: -x[1]):
        print(f"  {pred}: {count}")


if __name__ == "__main__":
    main()
