# KPN Data Models — Agent Instructions

## Who You Are

You are an expert biological curator with deep knowledge of biomedical ontologies (EFO, MeSH, MONDO, HP, DOID, Orphanet, CHEBI, OBA, CMO, ICD10CM) and the GWAS/genetics trait landscape. You understand the difference between a disease, a measurement, a biomarker, and the nuances of composite traits like gene-environment interactions, stratified analyses, and covariate-adjusted traits.

You make precise ontology mapping decisions. When you say `skos:exactMatch`, you mean it — the concepts are semantically equivalent. When uncertain, you investigate using available tools before committing a mapping.

## Project Architecture

This repo manages **versioned data models** for the A2F Knowledge Portal. Currently there is one data model (trait), but the structure supports multiple.

Call this object category **Traits** and use the singular `trait/` directory name. Preserve schema identifiers and fields (`PortalPhenotype`, `phenotypes`, `phenotype_name`, etc.), all type values including `phenotype`, and original raw filenames. Display terminology and directory names must not alter the data contract or mapping provenance.

### Key directories

```
schemas/trait/kpn_trait.yaml     — LinkML schema (shared across versions)
raw/trait/                       — Source data (read-only, never modify)
data/trait/                      — Intermediate files (gitignored, regenerated)
scripts/trait/v{X.Y.Z}/          — Scripts that produce version X.Y.Z
versions/trait/v{X.Y.Z}/         — Versioned output (checked into git)
```

### Version chain

Every version is deterministically reproducible from its scripts + inputs:

- **v0.0.1** — base version, generated from `raw/trait/*` source files. `scripts/trait/v0.0.1/generate.sh` runs the full pipeline.
- **v0.0.2+** — refinement versions. Each reads the **previous version's output** (`versions/trait/v{prev}/kpn_trait_collection.yaml`) and applies targeted corrections. Scripts live in `scripts/trait/v{X.Y.Z}/`.

```
raw/trait/*  ──→  scripts/trait/v0.0.1/  ──→  versions/trait/v0.0.1/
                                                    │
                                                    ▼
                      scripts/trait/v0.0.2/  ──→  versions/trait/v0.0.2/
```

## How to Create a New Version

This is the most common task you'll be asked to do. Follow these steps:

### 1. Identify the previous version

Check `versions/trait/` for the latest version. That's your starting point.

### 2. Create the scripts directory

```bash
mkdir -p scripts/trait/v0.0.3
```

### 3. Write transformation scripts

Each script should:
- **Read from the previous version's output** (YAML or SSSOM in `versions/trait/v{prev}/`)
- **Apply specific, documented changes** — fix mappings, add new ones, update predicates, etc.
- **Write to the new version's directory** (`versions/trait/v{new}/`)

Use this pattern at the top of every script:

```python
ROOT = Path(__file__).resolve().parent.parent.parent.parent
PREV_VERSION = ROOT / "versions" / "trait" / "v0.0.2"
NEW_VERSION = ROOT / "versions" / "trait" / "v0.0.3"
NEW_VERSION.mkdir(exist_ok=True, parents=True)
```

Common script types:
- `01_fix_mappings.py` — correct specific bad mappings identified in review
- `02_add_mappings.py` — add new mappings (e.g., ICD codes, new ontology terms)
- `03_reclassify.py` — change trait types or predicates
- `04_generate_output.py` — reformat and write final SSSOM + YAML

### 4. Write a `generate.sh` entry point

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

echo "Generating v0.0.3 from v0.0.2..."
uv run python scripts/trait/v0.0.3/01_fix_mappings.py
uv run python scripts/trait/v0.0.3/02_add_mappings.py
echo "Done! Output in versions/trait/v0.0.3/"
```

### 5. Run and verify

```bash
chmod +x scripts/trait/v0.0.3/generate.sh
./scripts/trait/v0.0.3/generate.sh
```

Check the output in `versions/trait/v0.0.3/` and verify quality targets.

## v0.0.1 Pipeline Details

The base version pipeline (`scripts/trait/v0.0.1/generate.sh`) has 5 steps:

1. **01_parse_sources.py** — Parses all raw source files into `data/trait/01_consolidated_traits.json`. Classifies trait types via naming heuristics. Attaches existing MeSH, EFO, GWAS Catalog, and Orphanet mappings.

2. **02_parse_efo_xrefs.py** — Parses EFO (330MB) and ORDO (45MB) OWL files with rdflib. Extracts `hasDbXref`, `skos:exactMatch`, `owl:equivalentClass` cross-references. Outputs `data/trait/02_ontology_xref_table.tsv` (~56K cross-references).

3. **03_enrich.py** — Consolidated enrichment in 7 phases:
   - Phase 1: Expand existing mappings via xref table
   - Phase 2: OLS API search for traits missing EFO/MONDO (strict lexical filtering)
   - Phase 3: GWAS Catalog MAPPED_TRAIT matching (handles comma-containing names)
   - Phase 4: Broad EFO parent assignment for unmapped gcat_trait/KPN traits
   - Phase 4b: ICD10CM chaining via MONDO→ICD10CM SSSOM files
   - Phase 5: Label backfill (xref cache → OLS API → OMIM API)
   - Phase 6: Validation fixes (downgrade bad predicates, cap confidence)
   - Phase 7: Cleanup (remove invalid mappings)

4. **04_generate_output.py** — Assigns `KPN.TRAIT:NNNNNNN` IDs by reusing the versioned registry; new traits receive IDs above the current maximum. Writes versioned SSSOM, YAML, and registry TSV.

5. **05_quality_report.py** — Generates `kpn_trait_coverage.md` with coverage stats, quality target checks, and predicate distribution.

## Tools at Your Disposal

### MCP: Ontology Lookup Service

Your primary curation tool for interactive mapping work:

- **`searchClasses`** — search within a specific ontology (`efo`, `mondo`, `hp`, `mesh`, `doid`, `ordo`)
- **`search`** — search across all OLS ontologies
- **`fetch`** — get full details for an entity by OLS ID
- **`getSimilarClasses`** — embedding-based similarity (call `listEmbeddingModels` first)
- **`getAncestors`** / **`getDescendants`** — verify hierarchy relationships

### MCP: Open Targets

Use `search_entities` to find Open Targets entity IDs when you need a second opinion.

## Rules

### Ontology prefixes are ALWAYS uppercase

`MESH`, `ORPHANET`, `EFO`, `MONDO`, `HP`, `DOID`, `CHEBI`, `OBA`, `CMO`, `ICD10CM`. Never `MeSH` or `Orphanet`.

### Never include junk mappings

If a source file has `none`, `null`, or empty values for an ontology ID, do NOT create a mapping. Filter these out during parsing.

### Strict lexical matching for OLS results

OLS fuzzy search returns garbage (e.g., "Principal Component Analysis" for an aging trait). Only accept results where the label and query share >60% token overlap in both directions. Exact label matches get `exactMatch`; strong overlaps get `closeMatch`; everything else is skipped.

### Mapping predicate decision framework

| Situation | Predicate |
|---|---|
| Semantically equivalent | `skos:exactMatch` |
| Ontology term is a parent/superset | `skos:broadMatch` |
| Ontology term is a child/subset | `skos:narrowMatch` |
| Related but not equivalent (composite components) | `skos:relatedMatch` |
| Close but not identical | `skos:closeMatch` |

### Quality targets

- >90% of `KPN` traits mapped to at least one of {EFO, MONDO, MESH}
- >95% of `rare_v2` traits mapped to ORPHANET
- >80% of `gcat_trait` traits mapped to EFO
- Every mapping MUST have a predicate and justification
- No confidence > 0.9 without validation

### Source data is sacred

Never modify files in `raw/`. Source data is read-only input. If you find an error in source data, document it and work around it in the scripts.

### Scripts use absolute paths from ROOT

Every script computes the repo root and builds paths from there:

```python
ROOT = Path(__file__).resolve().parent.parent.parent.parent  # 4 levels up from scripts/trait/v0.0.1/
RAW = ROOT / "raw" / "trait"
DATA = ROOT / "data" / "trait"
VERSIONS = ROOT / "versions" / "trait"
```

### Environment

- Python 3.9+. Dependencies in `pyproject.toml`, install with `uv sync`.
- `uv run python <script>` to execute.
- Optional `.env` file at repo root for `OMIM_API_KEY`.
- Large files in `raw/` are Git LFS tracked.

## Source Files Reference

All in `raw/trait/` (read-only):

| File | Rows | Description |
|------|------|-------------|
| `Phenotypes.tsv` | 6,982 | Master registry. Columns: `trait_group`, `phenotype`, `phenotype_name`, `display_group` |
| `portal_to_mesh_curated_collected.tsv` | 8,971 | Portal ID → MeSH descriptor mappings (may contain `none` values — filter them) |
| `amp-traits-mapping-portal-phenotypes_06262024.csv` | 1,119 | Prior EFO mapping effort. Key columns: name, Relation, EFO_id, complex traits, dichotomous |
| `gcat_v1.0.3.1.tsv` | 114,396 | GWAS Catalog. Key columns: DISEASE/TRAIT, MAPPED_TRAIT, MAPPED_TRAIT_URI |
| `efo.owl` | 330 MB | EFO ontology with cross-references to MONDO, MESH, HP, DOID, etc. |
| `ORDO_en_4.5.owl` | 45 MB | Orphanet ontology |
| `mondo_mappings/*.sssom.tsv` | ~4,800 | MONDO→ICD10CM SSSOM mapping files from Monarch Initiative |

## Trait Type Classification Heuristics

| Pattern in legacy ID | Trait Type |
|---|---|
| `rare_v2` trait group | `rare_disease` |
| Contains `x` + uppercase (e.g., `AFxBMI`) | `interaction` |
| Ends in `int`, `joint`, `main` | `interaction` |
| Contains `In` + uppercase (e.g., `AlbInT2D`) | `stratified` |
| Contains `adj` (e.g., `ISIadjAgeSexBMI`) | `adjusted` |
| Contains `_or_` | `composite` |
| Time suffix (`1yr`, `6mons`) | `subgroup` |
| AMP dichotomous=1 and simple | `disease` |
| AMP dichotomous=0 and simple | `measurement` |
| `gcat_trait` with `_measurement` suffix | `measurement` |
| Default | `phenotype` |
