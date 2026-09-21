# KPN Data Models

Unified, standards-compliant data models for phenotypes and other entities used across the [A2F Knowledge Portal](https://a2f.hugeamp.org/) and related Flannick Lab resources.

**Phenotype browser:** `https://broadinstitute.github.io/kpn-data-models/` (available after the first release deployment).

## What's in here

Each phenotype in the portal gets:

- A **stable numeric ID** (`KPN.TRAIT:0000001` through `KPN.TRAIT:0008402`)
- A **trait type classification** (disease, measurement, interaction, stratified, adjusted, etc.)
- **Cross-ontology mappings** to EFO, MESH, MONDO, HP, DOID, ORPHANET, CHEBI, OBA, CMO, and ICD10CM
- A **SKOS predicate** for each mapping (`exactMatch`, `broadMatch`, `closeMatch`, `narrowMatch`, `relatedMatch`)
- A **confidence score** and **provenance** for every mapping

Output is a [LinkML](https://linkml.io/) schema with data conforming to the [SSSOM](https://mapping-commons.github.io/sssom/) specification.

## Quick start

```bash
# Install dependencies
uv sync

# Rebuild the release offline, preserving all reviewed mappings
./scripts/phenotype/v0.0.1/generate.sh --from-release versions/phenotype/v0.0.1

# Re-enrich from source files (live ontology services may change results)
./scripts/phenotype/v0.0.1/generate.sh

# Fast rebuild (skip OWL parsing + API calls)
./scripts/phenotype/v0.0.1/generate.sh --skip-owl --skip-api
```

Output lands in `versions/phenotype/v0.0.1/`.

## Repository structure

```
portal-data-models/
├── schemas/phenotype/
│   └── portal_phenotype.yaml              # LinkML schema definition
│
├── scripts/phenotype/
│   └── v0.0.1/                            # Scripts that generate v0.0.1
│       ├── generate.sh                    # Single entry point
│       ├── 01_parse_sources.py            # Parse raw source files
│       ├── 02_parse_efo_xrefs.py          # Extract OWL cross-references
│       ├── 03_enrich.py                   # Enrichment pipeline (7 phases)
│       ├── 04_generate_output.py          # Assign IDs, write versioned output
│       └── 05_quality_report.py           # Coverage report
│
├── raw/phenotype/                         # Source data (read-only, do not modify)
│   ├── Phenotypes.tsv                     # 6,982 phenotypes (master registry)
│   ├── portal_to_mesh_curated_collected.tsv
│   ├── amp-traits-mapping-portal-phenotypes_06262024.csv
│   ├── gcat_v1.0.3.1.tsv                 # GWAS Catalog studies
│   ├── efo.owl                            # EFO ontology (330 MB, Git LFS)
│   ├── ORDO_en_4.5.owl                   # Orphanet ontology (45 MB, Git LFS)
│   └── mondo_mappings/                    # MONDO→ICD10CM SSSOM files
│
├── data/phenotype/                        # Intermediate files (gitignored)
│
├── versions/phenotype/                    # Versioned output (checked into git)
│   └── v0.0.1/
│       ├── kpn_trait_collection.yaml     # Full phenotype collection (LinkML)
│       ├── kpn_trait_flat.tsv            # Flattened one-row-per-mapping TSV
│       ├── kpn_trait_mappings.sssom.tsv  # SSSOM mapping set
│       ├── kpn_trait_registry.tsv        # ID registry
│       └── kpn_trait_coverage.md         # Quality report
│
├── .env                                   # API keys (optional, gitignored)
└── pyproject.toml
```

## Versioning philosophy

Release exports are checked in. Offline regeneration is reproducible from these snapshots; enrichment against live ontology APIs can change results.

### How versions work

Each version has its own scripts directory (`scripts/phenotype/v{X.Y.Z}/`) and output directory (`versions/phenotype/v{X.Y.Z}/`). This creates a complete chain of provenance:

- **v0.0.1** — the base version, with 8,402 phenotypes and 24,050 mappings, including 1,420 PIGEAN additions. Its IDs use `KPN.TRAIT:` with exactly the same numeric suffixes as the former `PORTAL:` identifiers. All release exports use the `kpn_trait_` filename prefix; the `portal_id` column is retained for compatibility. Use `--from-release` for an exact offline rebuild. Live re-enrichment must pass the regression checks before release.

- **v0.0.2, v0.0.3, ...** — refinement versions. Each builds on the *previous version's output* as its starting point (e.g., v0.0.2 reads `versions/phenotype/v0.0.1/kpn_trait_collection.yaml`). Scripts in these versions make targeted corrections: fixing bad mappings, adding missing ones, updating predicates, etc.

- **v0.1.0, v1.0.0, ...** — major versions for schema changes, new source data, or significant re-curation.

### Creating a new version

1. **Create the scripts directory:**
   ```bash
   mkdir -p scripts/phenotype/v0.0.2
   ```

2. **Write scripts that transform the previous version's output.** Your scripts should:
   - Read from `versions/phenotype/v0.0.1/kpn_trait_collection.yaml` (or the SSSOM/JSON)
   - Apply specific, documented changes (fix mappings, add new ones, etc.)
   - Write to `versions/phenotype/v0.0.2/`

   Example script structure:
   ```python
   # scripts/phenotype/v0.0.2/01_fix_mappings.py
   """Fix specific mapping issues identified in v0.0.1 review."""

   # Read v0.0.1 output
   with open(VERSIONS / "v0.0.1" / "kpn_trait_collection.yaml") as f:
       data = yaml.safe_load(f)

   # Apply corrections
   for pheno in data["phenotypes"]:
       if pheno["portal_id"] == "KPN.TRAIT:0000042":
           # Fix: AF was mapped to wrong MeSH term
           ...

   # Write v0.0.2 output
   ```

3. **Include a `generate.sh`** that runs all scripts in order:
   ```bash
   #!/usr/bin/env bash
   # Generate v0.0.2 from v0.0.1 + corrections
   set -euo pipefail
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
   cd "$REPO_ROOT"

   uv run python scripts/phenotype/v0.0.2/01_fix_mappings.py
   uv run python scripts/phenotype/v0.0.2/02_add_icd_codes.py
   # ... etc
   ```

4. **Commit everything** — scripts, output, and quality report:
   ```bash
   git add scripts/phenotype/v0.0.2/ versions/phenotype/v0.0.2/
   git commit -m "Phenotype mappings v0.0.2: fix AF mapping, add ICD codes"
   ```

### Version provenance chain

```
raw/phenotype/*  ──→  scripts/v0.0.1/  ──→  versions/v0.0.1/
                                                    │
                                                    ▼
                      scripts/v0.0.2/  ──→  versions/v0.0.2/
                                                    │
                                                    ▼
                      scripts/v0.0.3/  ──→  versions/v0.0.3/
```

Anyone can verify any version by running its scripts. v0.0.1 regenerates from source. v0.0.2 regenerates from v0.0.1's output. And so on.

## v0.0.1 pipeline

The base version runs 5 steps via `generate.sh`:

| Step | Script | What it does | Time |
|------|--------|-------------|------|
| 1 | `01_parse_sources.py` | Parse Phenotypes.tsv, MeSH mappings, AMP/EFO mappings, GWAS Catalog, Orphanet IDs | ~5s |
| 2 | `02_parse_efo_xrefs.py` | Extract cross-references from EFO and ORDO OWL files | ~75s |
| 3 | `03_enrich.py` | 7-phase enrichment: xref expansion, OLS API, GWAS Catalog, broad EFO, ICD10CM chaining, label backfill, validation | ~4 min |
| 4 | `04_generate_output.py` | Assign KPN.TRAIT IDs, generate SSSOM + YAML + registry + flattened TSV | ~5s |
| 5 | `05_quality_report.py` | Generate mapping coverage report | ~2s |

Flags: `--skip-owl` reuses cached OWL cross-references. `--skip-api` skips OLS/OMIM API calls.

## v0.0.1 coverage

| Target | Result |
|--------|--------|
| >90% portal phenotypes mapped to EFO/MONDO/MESH | 100% |
| >95% rare disease phenotypes mapped to ORPHANET | 100% |
| >80% GWAS Catalog traits mapped to EFO | 100% |

## Reviewing mappings

Every version includes `kpn_trait_flat.tsv` — a flattened one-row-per-mapping TSV with all phenotype and mapping fields. Open it in Excel, Google Sheets, or any dashboard tool to browse, filter, and spot-check mappings.

Key columns for review:
- `gwas_source_category` — source collection (portal, gcat_trait, rare_v2)
- `legacy_trait_group` — original display group from Phenotypes.tsv
- `trait_group` — standardized biological category (30 groups, consolidated from 55 legacy groups)
- `mapping_predicate` — filter by `skos:exactMatch` to review the highest-confidence mappings
- `confidence` — sort low-to-high to find the weakest mappings

To fix issues, create a new version with correction scripts (see [Creating a new version](#creating-a-new-version)).

## Contributing

1. **Found a bad mapping?** Open an issue with the phenotype name, the wrong mapping, and what the correct one should be.

2. **Want to fix mappings?** Create a new version with correction scripts (see [Creating a new version](#creating-a-new-version)), then open a PR.

3. **Adding a new data model?** Create subdirectories under `schemas/`, `scripts/`, `raw/`, and `versions/` (e.g., `schemas/variant/`). Follow the phenotype pattern.

### PR checklist

- [ ] Scripts in `scripts/phenotype/v{X.Y.Z}/` with a `generate.sh`
- [ ] Output in `versions/phenotype/v{X.Y.Z}/` with all files
- [ ] Quality report shows all targets passing
- [ ] No invalid target IDs (`MESH:none`, etc.)
- [ ] All ontology prefixes are uppercase (`MESH`, `ORPHANET`, not `MeSH`, `Orphanet`)

## Git LFS

Large source files are stored with [Git LFS](https://git-lfs.github.com/).

```bash
# Install (macOS)
brew install git-lfs

# After cloning
git lfs install
git lfs pull
```

Tracked: `raw/**/*.owl`, `raw/**/*.tsv` (see `.gitattributes`).

## Dependencies

Install with `uv sync`. Key packages: `linkml`, `rdflib`, `pandas`, `aiohttp`, `python-dotenv`.

## Optional: OMIM labels

Create `.env` at repo root with `OMIM_API_KEY=your_key_here` ([get one](https://omim.org/api)). Without it, OMIM mappings are included but without labels.

## GitHub Pages and release checks

The phenotype browser is generated from the **latest stable GitHub release**. Each trait has a permanent path such as `/kpn-data-models/kpn.trait/0000001/`, containing its names, classification, mappings, confidence, provenance, and JSON download. A searchable catalogue and complete release downloads are included.

```bash
uv run python -m unittest discover -s tests -v
uv run python scripts/site/build.py --data-dir versions/phenotype/v0.0.1 --release v0.0.1
python3 -m http.server 8000 --directory site/_build
```

See [Pages setup, release workflow, and regression checks](docs/github-pages.md) for the first deployment and future releases.
