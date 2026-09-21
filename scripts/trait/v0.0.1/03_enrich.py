#!/usr/bin/env python3
"""Step 3 (consolidated): Enrich phenotype mappings.

Combines the logic from:
  - 03_ols_bulk_lookup.py     — OLS API search + xref expansion
  - 03b_fix_gwas_matching.py  — GWAS Catalog MAPPED_TRAIT matching
  - 03c_fix_comma_traits.py   — comma-containing MAPPED_TRAIT matching
  - 03d_backfill_labels.py    — label backfill from xref table + OLS API
  - 03e_backfill_omim_labels.py — OMIM label backfill (optional)
  - 04_curate_broad_efo.py    — broad EFO parent for unmapped gcat/portal traits
  - 08_fix_flagged_mappings.py — validation fixes

Reads:
  - data/trait/01_consolidated_traits.json   (from Step 1)
  - data/trait/02_ontology_xref_table.tsv        (from Step 2)
  - raw/trait/gcat_v1.0.3.1.tsv                  (GWAS Catalog)
  - .env  (optional, for OMIM_API_KEY)

Writes:
  - data/trait/03_ols_enriched_mappings.json
  - data/trait/03_ols_lookup_log.tsv

Dependencies: aiohttp, pandas, python-dotenv
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

import aiohttp
import pandas as pd

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]

# ──────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent.parent
RAW = ROOT / "raw" / "trait"
DATA = ROOT / "data" / "trait"

# ──────────────────────────────────────────────────────────
# OLS API settings
# ──────────────────────────────────────────────────────────
OLS_BASE = "https://www.ebi.ac.uk/ols4/api"
TARGET_ONTOLOGIES = ["efo", "mondo", "hp", "doid", "mesh"]
MAX_CONCURRENT = 8
RETRY_DELAY = 2
MAX_RETRIES = 3

# ──────────────────────────────────────────────────────────
# IRI/CURIE conversion
# ──────────────────────────────────────────────────────────
IRI_PATTERNS = {
    "EFO": re.compile(r"http://www\.ebi\.ac\.uk/efo/EFO_(\d+)"),
    "MONDO": re.compile(r"http://purl\.obolibrary\.org/obo/MONDO_(\d+)"),
    "HP": re.compile(r"http://purl\.obolibrary\.org/obo/HP_(\d+)"),
    "DOID": re.compile(r"http://purl\.obolibrary\.org/obo/DOID_(\d+)"),
    "CHEBI": re.compile(r"http://purl\.obolibrary\.org/obo/CHEBI_(\d+)"),
    "ORPHANET": re.compile(r"http://www\.orpha\.net/ORDO/Orphanet_(\d+)"),
    "MESH": re.compile(r"http://id\.nlm\.nih\.gov/mesh/([A-Z0-9]+)"),
}

IRI_PREFIXES = {
    "http://www.ebi.ac.uk/efo/EFO_": "EFO:",
    "http://purl.obolibrary.org/obo/MONDO_": "MONDO:",
    "http://purl.obolibrary.org/obo/HP_": "HP:",
    "http://purl.obolibrary.org/obo/DOID_": "DOID:",
    "http://purl.obolibrary.org/obo/CHEBI_": "CHEBI:",
    "http://purl.obolibrary.org/obo/OBA_": "OBA:",
    "http://purl.obolibrary.org/obo/CMO_": "CMO:",
    "http://www.orpha.net/ORDO/Orphanet_": "ORPHANET:",
    "http://id.nlm.nih.gov/mesh/": "MESH:",
}

ONTOLOGY_LABELS = {
    "EFO": "EFO",
    "MONDO": "MONDO",
    "HP": "HP",
    "DOID": "DOID",
    "CHEBI": "CHEBI",
    "OBA": "OBA",
    "CMO": "CMO",
    "Orphanet": "ORPHANET",
    "ORPHANET": "ORPHANET",
    "MeSH": "MESH",
    "MESH": "MESH",
    "GO": "GO",
    "OMIM": "OMIM",
    "NCIT": "NCIT",
}

CURIE_TO_OLS = {
    "EFO": ("efo", "http://www.ebi.ac.uk/efo/EFO_{}"),
    "MONDO": ("mondo", "http://purl.obolibrary.org/obo/MONDO_{}"),
    "HP": ("hp", "http://purl.obolibrary.org/obo/HP_{}"),
    "DOID": ("doid", "http://purl.obolibrary.org/obo/DOID_{}"),
    "CHEBI": ("chebi", "http://purl.obolibrary.org/obo/CHEBI_{}"),
    "OBA": ("oba", "http://purl.obolibrary.org/obo/OBA_{}"),
    "CMO": ("cmo", "http://purl.obolibrary.org/obo/CMO_{}"),
    "ORPHANET": ("ordo", "http://www.orpha.net/ORDO/Orphanet_{}"),
    "MESH": ("mesh", "http://id.nlm.nih.gov/mesh/{}"),
    "GO": ("go", "http://purl.obolibrary.org/obo/GO_{}"),
    "OMIM": (None, None),
    "NCIT": ("ncit", "http://purl.obolibrary.org/obo/NCIT_{}"),
}


def iri_to_curie(iri: str) -> str | None:
    """Convert an IRI to a CURIE using known patterns."""
    for prefix, pattern in IRI_PATTERNS.items():
        m = pattern.match(iri)
        if m:
            return f"{prefix}:{m.group(1)}"
    return None


def uri_to_curie(uri: str) -> str:
    """Convert a URI to a CURIE using prefix matching (broader than iri_to_curie)."""
    for prefix, curie_prefix in IRI_PREFIXES.items():
        if uri.startswith(prefix):
            return f"{curie_prefix}{uri[len(prefix):]}"
    # Generic OBO fallback
    if uri.startswith("http://purl.obolibrary.org/obo/"):
        local = uri[len("http://purl.obolibrary.org/obo/"):]
        if "_" in local:
            parts = local.split("_", 1)
            return f"{parts[0]}:{parts[1]}"
    return uri


def ontology_from_curie(curie: str) -> str:
    """Get the canonical ontology label for a CURIE prefix."""
    prefix = curie.split(":")[0]
    return ONTOLOGY_LABELS.get(prefix, prefix)


def curie_to_iri(curie: str) -> tuple[str | None, str | None]:
    """Convert a CURIE to (ols_ontology_id, iri) for OLS API calls."""
    if ":" not in curie:
        return None, None
    prefix, local = curie.split(":", 1)
    info = CURIE_TO_OLS.get(prefix)
    if not info or not info[0]:
        return None, None
    return info[0], info[1].format(local)


# ──────────────────────────────────────────────────────────
# Lexical matching utilities
# ──────────────────────────────────────────────────────────
_STOPWORDS = {
    "a", "an", "the", "of", "in", "and", "or", "to", "for", "by",
    "with", "on", "at", "is", "are", "was",
}


def _normalize_tokens(s: str) -> set[str]:
    """Tokenize and normalize a string for comparison."""
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return {w for w in s.split() if w and w not in _STOPWORDS}


def _is_strong_lexical_match(query: str, label: str) -> bool:
    """Check if query and label are strong lexical matches.

    Requires >60% token overlap in BOTH directions.
    """
    q_tokens = _normalize_tokens(query)
    l_tokens = _normalize_tokens(label)
    if not q_tokens or not l_tokens:
        return False
    overlap = q_tokens & l_tokens
    q_overlap = len(overlap) / len(q_tokens)
    l_overlap = len(overlap) / len(l_tokens)
    return q_overlap > 0.6 and l_overlap > 0.6


# ──────────────────────────────────────────────────────────
# Validation utilities (Phase 6)
# ──────────────────────────────────────────────────────────
_VALIDATION_STOPWORDS = {
    "a", "an", "the", "of", "in", "and", "or", "to", "for", "by", "with",
    "on", "at", "is", "are", "was", "not", "no", "type", "level", "levels",
    "blood", "serum", "plasma", "measurement", "other",
}

GENERIC_TERMS = {
    "disease", "measurement", "phenotype", "disorder", "syndrome",
    "protein measurement", "experimental factor", "information content entity",
}

DISEASE_KEYWORDS = {
    "disease", "syndrome", "disorder", "carcinoma", "cancer",
    "lymphoma", "leukemia", "sarcoma",
}
MEASUREMENT_KEYWORDS = {"measurement", "assay", "level of", "concentration"}


def _tokenize_for_validation(s: str) -> set[str]:
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return {w for w in s.split() if w and w not in _VALIDATION_STOPWORDS}


def _token_overlap(a: str, b: str) -> float:
    ta = _tokenize_for_validation(a)
    tb = _tokenize_for_validation(b)
    if not ta or not tb:
        return 0.0
    overlap = ta & tb
    return min(len(overlap) / len(ta), len(overlap) / len(tb))


# ──────────────────────────────────────────────────────────
# Broad EFO tables (Phase 4)
# ──────────────────────────────────────────────────────────
BROAD_EFO_BY_GROUP = {
    "PROTEIN_BIOLOGY": ("EFO:0004747", "protein measurement"),
    "IMMUNOLOGICAL": ("EFO:0004421", "immune system measurement"),
    "PHARMACOGENOMICS": ("EFO:0010118", "response to drug"),
    "NEUROLOGICAL": ("EFO:0003929", "neurological measurement"),
    "HEMATOLOGICAL": ("EFO:0004503", "hematological measurement"),
    "LIPIDS": ("EFO:0004529", "lipid measurement"),
    "ENDOCRINE": ("EFO:0004530", "endocrine measurement"),
    "MUSCULOSKELETAL": ("EFO:0004505", "musculoskeletal measurement"),
    "METABOLITE": ("EFO:0004725", "metabolite measurement"),
    "NUTRITIONAL": ("EFO:0001444", "measurement"),
    "CANCER": ("EFO:0000311", "cancer"),
    "DIGESTIVE": ("EFO:0000405", "digestive system disease"),
    "DERMATOLOGICAL": ("EFO:0003931", "dermatological measurement"),
    "REPRODUCTIVE_TRAITS": ("EFO:0001444", "measurement"),
    "VASCULAR": ("EFO:0004298", "cardiovascular measurement"),
    "INFECTIOUS": ("EFO:0005741", "infectious disease"),
    "HEPATIC": ("EFO:0001444", "measurement"),
    "GLYCEMIC": ("EFO:0004468", "glycemic measurement"),
    "OCULAR": ("EFO:0004578", "ophthalmic measurement"),
    "DEVELOPMENTAL": ("EFO:0001444", "measurement"),
}
DEFAULT_BROAD_EFO = ("EFO:0001444", "measurement")


# ──────────────────────────────────────────────────────────
# OLS async helpers
# ──────────────────────────────────────────────────────────
async def ols_search(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    query: str,
    ontologies: list[str] | None = None,
    exact: bool = False,
) -> list[dict]:
    """Search OLS for a query string."""
    params: dict = {"q": query, "rows": 10, "type": "class"}
    if ontologies:
        params["ontology"] = ",".join(ontologies)
    if exact:
        params["exact"] = "true"

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    f"{OLS_BASE}/search",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data.get("response", {}).get("docs", [])
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
    return []


async def ols_fetch_label(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    ontology_id: str,
    iri: str,
) -> str | None:
    """Fetch a term label from OLS by ontology and IRI."""
    encoded_iri = quote(quote(iri, safe=""))
    url = f"{OLS_BASE}/ontologies/{ontology_id}/terms/{encoded_iri}"

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return data.get("label", None)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
    return None


# ──────────────────────────────────────────────────────────
# OMIM async helper
# ──────────────────────────────────────────────────────────
OMIM_API_BASE = "https://api.omim.org/api"


async def fetch_omim_labels(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    mim_numbers: list[str],
    api_key: str,
) -> dict[str, str]:
    """Fetch labels for a batch of OMIM MIM numbers (up to 20 at a time)."""
    labels: dict[str, str] = {}
    params = {
        "mimNumber": ",".join(mim_numbers),
        "include": "geneMap",
        "format": "json",
        "apiKey": api_key,
    }
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(
                    f"{OMIM_API_BASE}/entry",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                    if resp.status != 200:
                        return labels
                    data = await resp.json()
                    entries = data.get("omim", {}).get("entryList", [])
                    for item in entries:
                        entry = item.get("entry", {})
                        mim = str(entry.get("mimNumber", ""))
                        title = entry.get("titles", {}).get("preferredTitle", "")
                        if mim and title:
                            clean_title = title.split(";")[0].strip()
                            labels[mim] = clean_title
                    return labels
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                continue
    return labels


# ──────────────────────────────────────────────────────────
# Xref table loader
# ──────────────────────────────────────────────────────────
def load_xref_table(path: Path) -> dict[str, list[dict]]:
    """Load xref table -> {source_id: [{target_id, target_ontology, mapping_predicate}]}."""
    xrefs: dict[str, list[dict]] = defaultdict(list)
    if not path.exists():
        print(f"  WARNING: {path} not found. Run Step 2 first.")
        return dict(xrefs)
    df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    for _, row in df.iterrows():
        xrefs[row["source_id"]].append(
            {
                "target_id": row["target_id"],
                "target_ontology": row["target_ontology"],
                "mapping_predicate": row["mapping_predicate"],
            }
        )
    print(f"  Loaded {len(xrefs)} source entities from xref table")
    return dict(xrefs)


def load_xref_labels(path: Path) -> dict[str, str]:
    """Load labels from xref table: {curie: label}."""
    labels: dict[str, str] = {}
    if not path.exists():
        return labels
    df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    for _, row in df.iterrows():
        sid = row["source_id"]
        slabel = row["source_label"]
        if sid and slabel:
            labels[sid] = slabel
    print(f"  Loaded {len(labels)} labels from xref table")
    return labels


# ──────────────────────────────────────────────────────────
# Coverage helper
# ──────────────────────────────────────────────────────────
def count_coverage(recs: list[dict], ontologies: list[str]) -> int:
    count = 0
    for r in recs:
        mapped_onts = {m["target_ontology"] for m in r.get("mappings", [])}
        if mapped_onts & set(ontologies):
            count += 1
    return count


# ══════════════════════════════════════════════════════════
# Phase 1: Xref expansion
# ══════════════════════════════════════════════════════════
def phase1_xref_expansion(records: list[dict], xref_table: dict[str, list[dict]]) -> int:
    """Expand existing mappings via the xref table."""
    added = 0
    for record in records:
        existing_ids = {m["target_id"] for m in record.get("mappings", [])}
        new_mappings: list[dict] = []
        for m in record["mappings"]:
            target_id = m["target_id"]
            if target_id in xref_table:
                for xref in xref_table[target_id]:
                    if (
                        xref["target_id"] not in existing_ids
                        and xref["target_id"] not in {nm["target_id"] for nm in new_mappings}
                    ):
                        new_mappings.append(
                            {
                                "target_id": xref["target_id"],
                                "target_ontology": xref["target_ontology"],
                                "mapping_predicate": xref["mapping_predicate"],
                                "confidence": 0.8,
                                "mapping_justification": "cross_reference",
                                "source": f"xref via {target_id}",
                            }
                        )
        record["mappings"].extend(new_mappings)
        added += len(new_mappings)
    return added


# ══════════════════════════════════════════════════════════
# Phase 2: OLS API search
# ══════════════════════════════════════════════════════════
async def phase2_ols_search(
    records: list[dict],
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    log_entries: list[dict],
) -> int:
    """Search OLS for phenotypes missing EFO/MONDO mappings."""
    added = 0

    async def _enrich_one(record: dict) -> int:
        nonlocal added
        phenotype_name = record["phenotype_name"]
        existing_mappings = record.get("mappings", [])
        existing_ids = {m["target_id"] for m in existing_mappings}

        has_efo = any(m["target_ontology"] == "EFO" for m in existing_mappings)
        has_mondo = any(m["target_ontology"] == "MONDO" for m in existing_mappings)

        if has_efo and has_mondo:
            return 0

        # Try exact search first, then fuzzy
        docs = await ols_search(session, sem, phenotype_name, TARGET_ONTOLOGIES, exact=True)
        if not docs:
            docs = await ols_search(session, sem, phenotype_name, TARGET_ONTOLOGIES, exact=False)

        query_lower = phenotype_name.lower().strip()
        count = 0

        for doc in docs[:10]:
            iri = doc.get("iri", "")
            label = doc.get("label", "")
            curie = iri_to_curie(iri)
            if not curie:
                continue
            ontology = ontology_from_curie(curie)
            if curie in existing_ids:
                continue

            label_lower = label.lower().strip()
            is_exact = label_lower == query_lower

            if is_exact:
                confidence = 0.85
                predicate = "skos:exactMatch"
            elif _is_strong_lexical_match(query_lower, label_lower):
                confidence = 0.7
                predicate = "skos:closeMatch"
            else:
                continue

            record["mappings"].append(
                {
                    "target_id": curie,
                    "target_label": label,
                    "target_ontology": ontology,
                    "mapping_predicate": predicate,
                    "confidence": confidence,
                    "mapping_justification": "lexical_match",
                    "source": "OLS API search",
                }
            )
            existing_ids.add(curie)
            count += 1

            log_entries.append(
                {
                    "phenotype": record["phenotype"],
                    "query": phenotype_name,
                    "result_curie": curie,
                    "result_label": label,
                    "is_exact": is_exact,
                    "confidence": confidence,
                }
            )
        return count

    batch_size = 50
    start = time.time()
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        results = await asyncio.gather(*[_enrich_one(r) for r in batch])
        added += sum(results)
        elapsed = time.time() - start
        done = i + len(batch)
        pct = done / len(records) * 100
        print(f"    {done}/{len(records)} ({pct:.0f}%) [{elapsed:.0f}s]")

    return added


# ══════════════════════════════════════════════════════════
# Phase 3: GWAS Catalog MAPPED_TRAIT (03b + 03c combined)
# ══════════════════════════════════════════════════════════
def phase3_gwas_mapped_trait(records: list[dict]) -> int:
    """Match phenotype_name against GWAS Catalog MAPPED_TRAIT values.

    Builds two lookups from the GWAS Catalog:
      1. Comma-split MAPPED_TRAIT tokens (lowered) -> set of URIs
      2. Full unsplit MAPPED_TRAIT string (lowered) -> set of URIs

    Matches gcat_trait phenotypes against both lookups.
    """
    gcat_file = RAW / "gcat_v1.0.3.1.tsv"
    if not gcat_file.exists():
        print("    WARNING: GWAS Catalog file not found, skipping Phase 3")
        return 0

    # Build both lookup tables in a single pass through the GWAS file
    split_trait_to_uris: dict[str, set[str]] = defaultdict(set)
    full_trait_to_uris: dict[str, set[str]] = defaultdict(set)

    with open(gcat_file, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            mapped_trait = row.get("MAPPED_TRAIT", "").strip()
            mapped_uri = row.get("MAPPED_TRAIT_URI", "").strip()
            if not mapped_trait or not mapped_uri:
                continue

            # Full unsplit string -> all associated URIs
            full_trait_to_uris[mapped_trait.lower()].update(
                u.strip() for u in mapped_uri.split(",") if u.strip()
            )

            # Comma-split traits paired with comma-split URIs
            traits = [t.strip() for t in mapped_trait.split(",")]
            uris = [u.strip() for u in mapped_uri.split(",")]
            for t, u in zip(traits, uris):
                if t and u:
                    split_trait_to_uris[t.lower()].add(u)

    print(f"    {len(split_trait_to_uris)} comma-split MAPPED_TRAIT values")
    print(f"    {len(full_trait_to_uris)} full MAPPED_TRAIT strings")

    # Build lookup of gcat_trait phenotypes by name
    gcat_indices: dict[str, int] = {}
    for i, r in enumerate(records):
        if r["gwas_source_category"] == "gcat_trait":
            gcat_indices[r["phenotype_name"].lower()] = i

    added = 0
    for name_lower, idx in gcat_indices.items():
        record = records[idx]
        existing_ids = {m["target_id"] for m in record.get("mappings", [])}

        # Collect all matching URIs from both lookups
        matched_uris: set[str] = set()
        if name_lower in split_trait_to_uris:
            matched_uris |= split_trait_to_uris[name_lower]
        if name_lower in full_trait_to_uris:
            matched_uris |= full_trait_to_uris[name_lower]

        for uri in matched_uris:
            curie = uri_to_curie(uri)
            if curie in existing_ids:
                continue
            prefix = curie.split(":")[0]
            ontology = ONTOLOGY_LABELS.get(prefix, prefix)
            record["mappings"].append(
                {
                    "target_id": curie,
                    "target_ontology": ontology,
                    "mapping_predicate": "skos:exactMatch",
                    "confidence": 0.9,
                    "mapping_justification": "gwas_catalog",
                    "source": "gcat_v1.0.3.1.tsv (MAPPED_TRAIT match)",
                }
            )
            existing_ids.add(curie)
            added += 1

    return added


# ══════════════════════════════════════════════════════════
# Phase 4: Broad EFO assignment
# ══════════════════════════════════════════════════════════
def phase4_broad_efo(records: list[dict]) -> int:
    """Assign broad EFO parent terms for unmapped gcat_trait and KPN phenotypes."""
    added = 0
    for r in records:
        if r["gwas_source_category"] not in ("gcat_trait", "KPN", "portal"):
            continue

        has_efo = any(m["target_ontology"] == "EFO" for m in r.get("mappings", []))
        if has_efo:
            continue

        display_group = r.get("legacy_trait_group", "")
        efo_id, efo_label = BROAD_EFO_BY_GROUP.get(display_group, DEFAULT_BROAD_EFO)

        # Override for protein level phenotypes
        name_lower = r["phenotype_name"].lower()
        if "level of" in name_lower and ("serum" in name_lower or "plasma" in name_lower):
            efo_id, efo_label = "EFO:0004747", "protein measurement"

        r["mappings"].append(
            {
                "target_id": efo_id,
                "target_label": efo_label,
                "target_ontology": "EFO",
                "mapping_predicate": "skos:broadMatch",
                "confidence": 0.7,
                "mapping_justification": "manual_curation",
                "source": "broad EFO parent assignment by display_group",
            }
        )
        added += 1

    return added


# ══════════════════════════════════════════════════════════
# Phase 4b: ICD10CM chaining via MONDO
# ══════════════════════════════════════════════════════════
def load_mondo_icd10cm_mappings() -> dict[str, list[dict]]:
    """Load MONDO→ICD10CM SSSOM files from raw/trait/mondo_mappings/."""
    mondo_dir = RAW / "mondo_mappings"
    if not mondo_dir.exists():
        return {}

    mappings: dict[str, list[dict]] = defaultdict(list)
    for f in mondo_dir.glob("*.sssom.tsv"):
        with open(f) as fh:
            for line in fh:
                if line.startswith("#") or line.startswith("subject_id\t"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 4:
                    mondo_id = parts[0]
                    icd_id = parts[3]
                    icd_label = parts[4] if len(parts) > 4 else ""
                    predicate = parts[2]
                    mappings[mondo_id].append({
                        "icd_id": icd_id,
                        "icd_label": icd_label,
                        "predicate": predicate,
                    })
    return dict(mappings)


def phase4b_icd10cm_chaining(
    records: list[dict],
    xref_table: dict[str, list[dict]],
) -> int:
    """Add ICD10CM mappings by chaining PORTAL→MONDO→ICD10CM."""
    mondo_to_icd = load_mondo_icd10cm_mappings()
    if not mondo_to_icd:
        print("    No MONDO→ICD10CM mapping files found in raw/trait/mondo_mappings/")
        return 0

    total_icd = sum(len(v) for v in mondo_to_icd.values())
    print(f"    Loaded {total_icd} MONDO→ICD10CM mappings across {len(mondo_to_icd)} MONDO terms")

    # Also build EFO→MONDO lookup from xref table for chaining
    efo_to_mondo: dict[str, set[str]] = defaultdict(set)
    for src_id, xrefs in xref_table.items():
        if src_id.startswith("EFO:"):
            for x in xrefs:
                if x["target_id"].startswith("MONDO:"):
                    efo_to_mondo[src_id].add(x["target_id"])
        elif src_id.startswith("MONDO:"):
            for x in xrefs:
                if x["target_id"].startswith("EFO:"):
                    efo_to_mondo[x["target_id"]].add(src_id)

    added = 0
    for r in records:
        existing_ids = {m["target_id"] for m in r.get("mappings", [])}

        # Collect all MONDO IDs (direct + via EFO chain)
        mondo_ids: set[str] = set()
        for m in r.get("mappings", []):
            tid = m["target_id"]
            if tid.startswith("MONDO:"):
                mondo_ids.add(tid)
            elif tid.startswith("EFO:"):
                mondo_ids |= efo_to_mondo.get(tid, set())

        # Chain to ICD10CM
        for mondo_id in mondo_ids:
            for icd_entry in mondo_to_icd.get(mondo_id, []):
                icd_id = icd_entry["icd_id"]
                if icd_id in existing_ids:
                    continue
                existing_ids.add(icd_id)
                r["mappings"].append({
                    "target_id": icd_id,
                    "target_label": icd_entry["icd_label"],
                    "target_ontology": "ICD10CM",
                    "mapping_predicate": icd_entry["predicate"],
                    "confidence": 0.8,
                    "mapping_justification": "cross_reference",
                    "source": f"MONDO SSSOM via {mondo_id}",
                })
                added += 1

    return added


# ══════════════════════════════════════════════════════════
# Phase 5: Label backfill
# ══════════════════════════════════════════════════════════
async def phase5_backfill_labels(
    records: list[dict],
    xref_labels: dict[str, str],
    session: aiohttp.ClientSession | None,
    sem: asyncio.Semaphore,
    omim_api_key: str | None,
) -> dict[str, int]:
    """Backfill missing target_label from xref table, OLS API, and OMIM API."""
    stats: dict[str, int] = {"from_xref": 0, "from_ols": 0, "from_omim": 0, "still_missing": 0}

    # Step A: Fill from xref label cache
    needs_ols: dict[str, None] = {}
    for r in records:
        for m in r.get("mappings", []):
            if not m.get("target_label", "").strip():
                curie = m["target_id"]
                if curie in xref_labels:
                    m["target_label"] = xref_labels[curie]
                    stats["from_xref"] += 1
                elif curie not in needs_ols:
                    needs_ols[curie] = None

    # Step B: Fetch from OLS API (skip OMIM CURIEs, handled separately)
    ols_curies = [c for c in needs_ols if not c.startswith("OMIM:")]
    ols_label_cache: dict[str, str] = {}

    if ols_curies and session is not None:
        print(f"    Fetching {len(ols_curies)} labels from OLS API...")
        start = time.time()

        async def _noop() -> str | None:
            return None

        batch_size = 50
        for i in range(0, len(ols_curies), batch_size):
            batch = ols_curies[i : i + batch_size]
            tasks: list[tuple[str, asyncio.Task]] = []
            for curie in batch:
                ontology_id, iri = curie_to_iri(curie)
                if ontology_id and iri:
                    tasks.append((curie, ols_fetch_label(session, sem, ontology_id, iri)))
                else:
                    tasks.append((curie, _noop()))

            results = await asyncio.gather(*[t[1] for t in tasks])
            for (curie, _), label in zip(tasks, results):
                if label:
                    ols_label_cache[curie] = label

            elapsed = time.time() - start
            done = min(i + batch_size, len(ols_curies))
            pct = done / len(ols_curies) * 100
            print(
                f"      {done}/{len(ols_curies)} ({pct:.0f}%) [{elapsed:.0f}s]"
                f" -- {len(ols_label_cache)} labels found"
            )

    # Apply OLS labels
    for r in records:
        for m in r.get("mappings", []):
            if not m.get("target_label", "").strip():
                curie = m["target_id"]
                if curie in ols_label_cache:
                    m["target_label"] = ols_label_cache[curie]
                    stats["from_ols"] += 1

    # Step C: OMIM labels (optional)
    omim_ids: set[str] = set()
    for r in records:
        for m in r.get("mappings", []):
            if (
                m.get("target_ontology") == "OMIM"
                and not m.get("target_label", "").strip()
                and m["target_id"].startswith("OMIM:")
            ):
                omim_ids.add(m["target_id"].split(":")[1])

    if omim_ids and omim_api_key:
        print(f"    Fetching {len(omim_ids)} OMIM labels...")
        omim_sem = asyncio.Semaphore(5)  # OMIM rate limits are stricter
        omim_label_cache: dict[str, str] = {}
        omim_list = sorted(omim_ids)
        start = time.time()

        batch_size = 20
        for i in range(0, len(omim_list), batch_size):
            batch = omim_list[i : i + batch_size]
            batch_labels = await fetch_omim_labels(session, omim_sem, batch, omim_api_key)
            omim_label_cache.update(batch_labels)
            elapsed = time.time() - start
            done = min(i + batch_size, len(omim_list))
            print(
                f"      {done}/{len(omim_list)} ({done / len(omim_list) * 100:.0f}%)"
                f" [{elapsed:.0f}s] -- {len(omim_label_cache)} labels"
            )

        for r in records:
            for m in r.get("mappings", []):
                if (
                    m.get("target_ontology") == "OMIM"
                    and not m.get("target_label", "").strip()
                ):
                    mim = m["target_id"].split(":")[1] if ":" in m["target_id"] else ""
                    if mim in omim_label_cache:
                        m["target_label"] = omim_label_cache[mim]
                        stats["from_omim"] += 1
    elif omim_ids:
        print(f"    Skipping {len(omim_ids)} OMIM labels (no OMIM_API_KEY)")

    # Count still missing
    stats["still_missing"] = sum(
        1 for r in records for m in r.get("mappings", [])
        if not m.get("target_label", "").strip()
    )
    return stats


# ══════════════════════════════════════════════════════════
# Phase 6: Validation fixes
# ══════════════════════════════════════════════════════════
def phase6_validation_fixes(records: list[dict]) -> Counter:
    """Downgrade predicates for generic exactMatches, type mismatches, etc."""
    fixes: Counter = Counter()

    for r in records:
        phenotype_name = r["phenotype_name"]
        trait_type = r.get("trait_type", "")
        name_lower = phenotype_name.lower()

        for m in r.get("mappings", []):
            target_label = m.get("target_label", "").strip()
            predicate = m.get("mapping_predicate", "")
            confidence = m.get("confidence", 0)
            justification = m.get("mapping_justification", "")

            # Fix 1: GENERIC_EXACT -- exactMatch to overly generic term
            if (
                predicate == "skos:exactMatch"
                and target_label
                and target_label.lower().strip() in GENERIC_TERMS
            ):
                m["mapping_predicate"] = "skos:broadMatch"
                m["confidence"] = min(confidence, 0.6)
                fixes["generic_exact->broadMatch"] += 1
                continue

            # Fix 2a: TYPE_MISMATCH -- measurement mapped as exactMatch to disease
            if (
                predicate == "skos:exactMatch"
                and target_label
                and trait_type == "measurement"
            ):
                label_lower = target_label.lower()
                if any(kw in label_lower for kw in DISEASE_KEYWORDS):
                    if not any(kw in name_lower for kw in DISEASE_KEYWORDS):
                        m["mapping_predicate"] = "skos:relatedMatch"
                        m["confidence"] = min(confidence, 0.5)
                        fixes["type_mismatch->relatedMatch"] += 1
                        continue

            # Fix 2b: TYPE_MISMATCH -- disease mapped as exactMatch to measurement
            if (
                predicate == "skos:exactMatch"
                and target_label
                and trait_type == "disease"
            ):
                label_lower = target_label.lower()
                if any(kw in label_lower for kw in MEASUREMENT_KEYWORDS):
                    if not any(kw in name_lower for kw in MEASUREMENT_KEYWORDS):
                        m["mapping_predicate"] = "skos:relatedMatch"
                        m["confidence"] = min(confidence, 0.5)
                        fixes["type_mismatch->relatedMatch"] += 1
                        continue

            # Fix 3: HIGH_CONF_UNJUSTIFIED -- lexical_match with confidence > 0.9
            if confidence and confidence > 0.9 and justification == "lexical_match":
                m["confidence"] = 0.85
                fixes["high_conf_adjusted"] += 1

            # Fix 4: LOW_OVERLAP_EXACT -- exactMatch from automated sources
            if (
                predicate == "skos:exactMatch"
                and target_label
                and justification in ("lexical_match", "cross_reference")
            ):
                overlap = _token_overlap(phenotype_name, target_label)
                if overlap < 0.2:
                    m["mapping_predicate"] = "skos:relatedMatch"
                    m["confidence"] = min(confidence, 0.5)
                    fixes["low_overlap_exact->relatedMatch"] += 1
                elif overlap < 0.3:
                    m["mapping_predicate"] = "skos:closeMatch"
                    m["confidence"] = min(confidence, 0.6)
                    fixes["low_overlap_exact->closeMatch"] += 1

    return fixes


# ══════════════════════════════════════════════════════════
# Phase 7: Cleanup
# ══════════════════════════════════════════════════════════
def phase7_cleanup(records: list[dict]) -> int:
    """Remove mappings with empty target_ontology or target_id containing 'none'."""
    removed = 0
    for r in records:
        original = r.get("mappings", [])
        cleaned = [
            m for m in original
            if m.get("target_ontology", "").strip()
            and "none" not in m.get("target_id", "").lower()
        ]
        removed += len(original) - len(cleaned)
        r["mappings"] = cleaned
    return removed


# ══════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════
async def main_async(skip_api: bool = False):
    print("=" * 60)
    print("Step 3 (consolidated): Enrich phenotype mappings")
    print("=" * 60)

    # ── Load inputs ───────────────────────────────────────
    print("\nLoading inputs...")
    consolidated_path = DATA / "01_consolidated_traits.json"
    if not consolidated_path.exists():
        print(f"ERROR: {consolidated_path} not found. Run Step 1 first.")
        sys.exit(1)

    with open(consolidated_path) as f:
        records: list[dict] = json.load(f)
    # Accept consolidated caches created before the source category rename.
    for record in records:
        if record["gwas_source_category"] == "portal":
            record["gwas_source_category"] = "KPN"
    print(f"  Loaded {len(records)} phenotype records")

    xref_table_path = DATA / "02_ontology_xref_table.tsv"
    xref_table = load_xref_table(xref_table_path)
    xref_labels = load_xref_labels(xref_table_path)

    # Load OMIM API key (optional)
    omim_api_key: str | None = None
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")
    omim_api_key = os.getenv("OMIM_API_KEY", "").strip() or None
    if omim_api_key:
        print("  OMIM_API_KEY found")
    else:
        print("  OMIM_API_KEY not found (OMIM label backfill will be skipped)")

    # Pre-enrichment coverage
    portal_recs = [r for r in records if r["gwas_source_category"] == "KPN"]
    gcat_recs = [r for r in records if r["gwas_source_category"] == "gcat_trait"]
    rare_recs = [r for r in records if r["gwas_source_category"] == "rare_v2"]

    print("\nPre-enrichment coverage:")
    print(f"  KPN     with EFO/MONDO : {count_coverage(portal_recs, ['EFO', 'MONDO'])}/{len(portal_recs)}")
    print(f"  gcat    with EFO/MONDO : {count_coverage(gcat_recs, ['EFO', 'MONDO'])}/{len(gcat_recs)}")
    print(f"  rare_v2 with Orphanet  : {count_coverage(rare_recs, ['ORPHANET'])}/{len(rare_recs)}")

    # ── Phase 1: Xref expansion ──────────────────────────
    print("\n" + "-" * 60)
    print("Phase 1: Xref expansion")
    print("-" * 60)
    n = phase1_xref_expansion(records, xref_table)
    print(f"  Added {n} mappings via xref expansion")

    # ── Phase 2: OLS API search ──────────────────────────
    log_entries: list[dict] = []
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    if not skip_api:
        print("\n" + "-" * 60)
        print("Phase 2: OLS API search")
        print("-" * 60)
        async with aiohttp.ClientSession() as session:
            n = await phase2_ols_search(records, session, sem, log_entries)
            print(f"  Added {n} mappings via OLS API")
    else:
        print("\n  Phase 2: Skipped (--skip-api)")

    # ── Phase 3: GWAS Catalog MAPPED_TRAIT ───────────
    print("\n" + "-" * 60)
    print("Phase 3: GWAS Catalog MAPPED_TRAIT matching")
    print("-" * 60)
    n = phase3_gwas_mapped_trait(records)
    print(f"  Added {n} mappings via GWAS Catalog MAPPED_TRAIT")

    # ── Phase 4: Broad EFO assignment ────────────────
    print("\n" + "-" * 60)
    print("Phase 4: Broad EFO assignment for unmapped gcat_trait + KPN phenotypes")
    print("-" * 60)
    n = phase4_broad_efo(records)
    print(f"  Added {n} broad EFO mappings")

    # ── Phase 4b: ICD10CM chaining ──────────────────
    print("\n" + "-" * 60)
    print("Phase 4b: ICD10CM chaining via MONDO")
    print("-" * 60)
    n = phase4b_icd10cm_chaining(records, xref_table)
    print(f"  Added {n} ICD10CM mappings")

    # ── Phase 5: Label backfill ──────────────────────
    print("\n" + "-" * 60)
    print("Phase 5: Label backfill (xref table + OLS API + OMIM)")
    print("-" * 60)
    if not skip_api:
        async with aiohttp.ClientSession() as session:
            label_stats = await phase5_backfill_labels(
                records, xref_labels, session, sem, omim_api_key
            )
    else:
        label_stats = await phase5_backfill_labels(
            records, xref_labels, None, sem, None
        )
    print(f"  From xref table : {label_stats['from_xref']}")
    print(f"  From OLS API    : {label_stats['from_ols']}")
    print(f"  From OMIM API   : {label_stats['from_omim']}")
    print(f"  Still missing   : {label_stats['still_missing']}")

    # ── Phase 6: Validation fixes ────────────────────────
    print("\n" + "-" * 60)
    print("Phase 6: Validation fixes")
    print("-" * 60)
    fixes = phase6_validation_fixes(records)
    if fixes:
        for fix_type, count in fixes.most_common():
            print(f"  {fix_type}: {count}")
        print(f"  Total fixes: {sum(fixes.values())}")
    else:
        print("  No fixes needed")

    # ── Phase 7: Cleanup ─────────────────────────────────
    print("\n" + "-" * 60)
    print("Phase 7: Cleanup (remove invalid mappings)")
    print("-" * 60)
    n = phase7_cleanup(records)
    print(f"  Removed {n} invalid mappings")

    # ── Write outputs ────────────────────────────────────
    print("\n" + "-" * 60)
    print("Writing outputs")
    print("-" * 60)

    output_path = DATA / "03_ols_enriched_mappings.json"
    with open(output_path, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {len(records)} enriched records to {output_path}")

    # Write OLS lookup log
    log_path = DATA / "03_ols_lookup_log.tsv"
    if log_entries:
        with open(log_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "phenotype", "query", "result_curie",
                    "result_label", "is_exact", "confidence",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerows(log_entries)
        print(f"  Wrote {len(log_entries)} log entries to {log_path}")

    # ── Summary ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    portal_enriched = [r for r in records if r["gwas_source_category"] == "KPN"]
    gcat_enriched = [r for r in records if r["gwas_source_category"] == "gcat_trait"]
    rare_enriched = [r for r in records if r["gwas_source_category"] == "rare_v2"]

    print("\nPost-enrichment coverage:")
    print(f"  KPN     with EFO/MONDO : {count_coverage(portal_enriched, ['EFO', 'MONDO'])}/{len(portal_enriched)}")
    print(f"  gcat    with EFO/MONDO : {count_coverage(gcat_enriched, ['EFO', 'MONDO'])}/{len(gcat_enriched)}")
    print(f"  rare_v2 with Orphanet  : {count_coverage(rare_enriched, ['ORPHANET'])}/{len(rare_enriched)}")

    total_mappings = sum(len(r.get("mappings", [])) for r in records)
    by_ontology: Counter = Counter()
    by_justification: Counter = Counter()
    for r in records:
        for m in r.get("mappings", []):
            by_ontology[m.get("target_ontology", "?")] += 1
            by_justification[m.get("mapping_justification", "?")] += 1

    print(f"\nTotal mappings: {total_mappings}")
    print("\nBy ontology:")
    for ont, count in sorted(by_ontology.items(), key=lambda x: -x[1]):
        print(f"  {ont}: {count}")
    print("\nBy justification:")
    for just, count in sorted(by_justification.items(), key=lambda x: -x[1]):
        print(f"  {just}: {count}")

    # Label coverage
    total_m = sum(len(r.get("mappings", [])) for r in records)
    has_label = sum(
        1 for r in records for m in r.get("mappings", [])
        if m.get("target_label", "").strip()
    )
    if total_m:
        print(f"\nLabel coverage: {has_label}/{total_m} ({has_label / total_m * 100:.1f}%)")

    unmapped = [r for r in records if not r.get("mappings")]
    print(f"Remaining unmapped: {len(unmapped)}")

    print("\nDone.")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-api", action="store_true", help="Skip OLS/OMIM API calls")
    args = parser.parse_args()
    asyncio.run(main_async(skip_api=args.skip_api))


if __name__ == "__main__":
    main()
