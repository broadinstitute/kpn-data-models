# Portal Data Models — Agent Instructions

## Project Purpose

Build a unified, standards-compliant data model for all phenotypes used across the A2F Knowledge Portal and related Flannick Lab resources. The goal is to:

1. Assign every phenotype a new **stable numeric Portal Phenotype ID** (e.g., `KPN.TRAIT:0000001`)
2. Preserve the **legacy text-based ID** (e.g., `AF`, `gcat_trait_Moyamoya_disease`, `HermanskyPudlak_syndrome_Orphanet_79430`)
3. Map each phenotype to as many external ontology IDs as possible (EFO, MeSH, MONDO, HP, DOID, Orphanet, CHEBI, OBA, CMO)
4. Classify each mapping relationship using SKOS predicates (`skos:exactMatch`, `skos:broadMatch`, `skos:narrowMatch`, `skos:relatedMatch`, `skos:closeMatch`)
5. Classify each phenotype by **trait type** (disease, measurement, biomarker, composite/interaction, adjusted, subgroup, etc.)
6. Output everything as a **LinkML schema** with data conforming to the **SSSOM (Simple Standard for Sharing Ontological Mappings)** specification

---

## Source Data Files

All source files are in `raw/`. **Do not modify source files** — treat them as read-only inputs.

### 1. `Phenotypes.tsv` — The Master Phenotype Registry (PRIMARY SOURCE OF TRUTH)

- **6,982 phenotypes** (no header row label — columns are tab-separated)
- Columns: `trait_group | phenotype | phenotype_name | display_group`
- Three trait groups:
  - **`portal`** (1,437 rows): Core portal phenotypes. Legacy IDs like `AF`, `BMI`, `AFxBMI`, `AlbInT2D`
  - **`gcat_trait`** (4,022 rows): GWAS Catalog-sourced traits. IDs have `gcat_trait_` prefix + snake_case name (e.g., `gcat_trait_Moyamoya_disease`)
  - **`rare_v2`** (1,523 rows): Rare disease phenotypes. IDs embed Orphanet codes (e.g., `HermanskyPudlak_syndrome_Orphanet_79430` → Orphanet:79430)
- `display_group` provides a disease-area category (e.g., `CARDIOVASCULAR`, `GLYCEMIC`, `NEUROLOGICAL` — ~50 categories)
- `phenotype_name` is the human-readable label — this is key for ontology matching

### 2. `portal_to_mesh_curated_collected.tsv` — Curated MeSH Mappings

- **8,971 rows** mapping portal IDs → MeSH descriptor IDs (e.g., `AF → D001281`)
- **1,745 unique MeSH IDs**, **6,943 unique portal IDs**
- Many portal IDs map to **multiple MeSH IDs** (composite phenotypes). For example:
  - `AFxBMI` → `D001281` (Atrial Fibrillation) AND `D015992` (Body Mass Index)
  - `AlbInT2D` → `D000419` (Albumin) AND `D003924` (Diabetes Mellitus, Type 2)
- This file covers portal AND gcat_trait AND rare_v2 phenotypes — not just the `portal` group
- These mappings are a mix of automated and manual curation — trust them as high quality starting points

### 3. `amp-traits-mapping-portal-phenotypes_06262024.csv` — AMP/EFO Mapping Effort

- **1,119 rows** — a prior colleague's attempt to map portal phenotypes to EFO
- Columns: `id, name, description, dichotomous, group, PMID example, PMID in GWAS CATALOG?, complex traits, Relation, EFO_term, API_EFO_ID, EFO_id, comments, supported by OLS, supported by Zooma, GWAS catalog UI search, Lizzy's suggestion, suggestion applied, Maria's suggestion, import_new_terms`
- Key columns for this work:
  - `name`: the portal phenotype legacy ID
  - `description`: human-readable description
  - `complex traits`: `simple` (808) or `complex` (196) — indicates if the trait is a single concept or a composite
  - `Relation`: mapping quality — `Exact match` (433), `Match to parent` (414 — these are broadMatch), `need import` (20), etc.
  - `EFO_id`: the mapped EFO ID (e.g., `EFO_0000275`) — some have CHEBI or CMO IDs instead
  - `comments`, `Lizzy's suggestion`, `Maria's suggestion`: manual curation notes — read these for edge cases
- **WARNING**: This CSV has inconsistent quoting and some messy fields. Parse carefully.

### 4. `gcat_v1.0.3.1.tsv` — GWAS Catalog Studies (114,396 rows)

- Full GWAS Catalog study table. Key columns:
  - Column 8 `DISEASE/TRAIT`: free-text trait name
  - Column 13 `MAPPED_TRAIT`: standardized EFO trait label(s), comma-separated
  - Column 14 `MAPPED_TRAIT_URI`: corresponding EFO/MONDO/OBA IRIs, comma-separated
  - Column 19 `BACKGROUND TRAIT`: for interaction studies
  - Column 20-21 `MAPPED BACKGROUND TRAIT` / `MAPPED BACKGROUND TRAIT URI`
  - Column 25 `GXE`: `yes`/`no` — flags gene-environment interaction studies (881 are `yes`)
- Use this to **extract EFO/MONDO mappings for gcat_trait phenotypes** by matching `DISEASE/TRAIT` or `MAPPED_TRAIT` to the `phenotype_name` from `Phenotypes.tsv`

### 5. `gcat_v1.0.3.1.1.tsv` — GWAS Catalog Ancestry/Sample Data (165,174 rows)

- Companion file with sample/ancestry info. Less relevant for ontology mapping but may help resolve ambiguous traits.

### 6. `efo.owl` and `ORDO_en_4.5.owl` — Ontology Files

- Local copies of EFO and Orphanet (ORDO) ontologies in OWL format
- These are large (330MB and 44MB). Use them for **cross-reference extraction** — EFO entities often have `hasDbXref` annotations pointing to MeSH, MONDO, HP, DOID, etc.
- Parse with `owlready2`, `rdflib`, or `pronto` (Python ontology libraries)

---

## Phenotype Classification Taxonomy

Define a LinkML enum (or SKOS concept scheme) for phenotype trait types. Based on the data, the following types exist:

### Simple Trait Types
- **`disease`**: A diagnosable disease or condition (e.g., `AF` → Atrial Fibrillation, `AD` → Alzheimer Disease)
- **`measurement`**: A quantitative measurement or biomarker level (e.g., `BMI`, `ALBUMIN`, `AUCins`)
- **`phenotype`**: An observable characteristic that isn't a disease or measurement (e.g., `CerebellarVol` — Total cerebellar volume)
- **`rare_disease`**: Rare disease from Orphanet (all `rare_v2` entries)

### Composite/Complex Trait Types
- **`interaction`**: GxE or trait-trait interaction study (identified by `x` separator in portal IDs, e.g., `AFxBMI` = AF × BMI interaction, `AFxSEX` = AF × sex interaction, `SmokingT2Dint`)
- **`stratified`**: Trait measured within a subpopulation or conditional on another trait (e.g., `AlbInT2D` = albumin in T2D patients, `AnyCVDinT2D`, `AllDKDvControl_DM`)
- **`adjusted`**: Trait adjusted for covariates (e.g., `ISIadjAgeSexBMI`, `CKDextremesadjHbA1cBMI`, `BMI_adjSMK`)
- **`subgroup`**: Age/sex/ancestry-specific subgroup (e.g., `AFxAGEo65` = AF in over-65, `BMI1yr` = BMI at 1 year)
- **`composite`**: Combined phenotypes or alternative definitions (e.g., `AD_or_AD_history`, `AfibFlutter`)

For composite types, the mapping should capture **all component concepts**. For example:
- `AFxBMI` should map to BOTH `EFO_0000275` (atrial fibrillation) AND `EFO_0004340` (body mass index), with the relationship to each being `skos:relatedMatch` and metadata indicating it's an interaction.

---

## Ontology Mapping Strategy

### Phase 1: Harvest Existing Mappings (Automated)

Write a Python script (`scripts/harvest_existing_mappings.py`) that consolidates what we already have:

1. **From `portal_to_mesh_curated_collected.tsv`**: Extract all `portal_id → MeSH` pairs
2. **From `amp-traits-mapping-portal-phenotypes_06262024.csv`**: Extract all `name → EFO_id` pairs with their `Relation` type
   - Map `Relation` values to SKOS: `Exact match` → `skos:exactMatch`, `Match to parent` → `skos:broadMatch`
3. **From `Phenotypes.tsv` rare_v2 rows**: Extract embedded Orphanet IDs from the phenotype column (regex: `Orphanet_(\d+)`)
4. **From `gcat_v1.0.3.1.tsv`**: For each `gcat_trait` phenotype, find matching GWAS Catalog studies and extract `MAPPED_TRAIT_URI` (gives EFO/MONDO IRIs directly)
5. **From `efo.owl`**: Parse cross-references (`hasDbXref`, `exactMatch` annotations) to build an EFO ↔ MeSH ↔ MONDO ↔ HP ↔ DOID lookup table. This is the most valuable step — EFO already contains most cross-ontology links.

Output: A single consolidated TSV with columns:
```
portal_phenotype_id | source_file | target_ontology | target_id | target_label | mapping_predicate | confidence | notes
```

### Phase 2: Fill Gaps via OLS API (Automated)

Write a script (`scripts/ols_bulk_lookup.py`) that takes unmapped phenotypes and queries the OLS (Ontology Lookup Service) REST API:

- Base URL: `https://www.ebi.ac.uk/ols4/api/`
- For each `phenotype_name`, search across ontologies:
  ```
  GET /search?q={phenotype_name}&ontology=efo,mondo,hp,doid,mesh&exact=true
  GET /search?q={phenotype_name}&ontology=efo,mondo,hp,doid,mesh  (if exact fails)
  ```
- Use `aiohttp` for async parallel requests (respect rate limits — max 10 concurrent)
- For each MeSH ID we already have, fetch its OLS entry and extract cross-references:
  ```
  GET /ontologies/mesh/terms?iri=http://id.nlm.nih.gov/mesh/{mesh_id}
  ```

Output: Append to the consolidated mapping file from Phase 1.

### Phase 3: Expert Curation via MCP Tools (Agent-Assisted)

For phenotypes that remain unmapped or have ambiguous matches after Phases 1-2, use the **ontology-lookup-service MCP tools** interactively:

- `mcp__ontology-lookup-service__searchClasses` — search within a specific ontology
- `mcp__ontology-lookup-service__search` — search across all OLS ontologies
- `mcp__ontology-lookup-service__fetch` — fetch full details for an entity
- `mcp__ontology-lookup-service__getSimilarClasses` — embedding-based similarity (call `listEmbeddingModels` first)
- `mcp__ontology-lookup-service__getAncestors` / `getDescendants` — navigate hierarchies

**Prioritize curation effort**: Focus on the 1,437 `portal` phenotypes first (they're the most important and most complex). The `gcat_trait` phenotypes should mostly resolve automatically via GWAS Catalog mappings. The `rare_v2` phenotypes already have Orphanet IDs embedded.

For **composite phenotypes** (interaction/stratified/adjusted), decompose them:
1. Identify the component concepts (e.g., `AFxBMI` → "atrial fibrillation" + "body mass index")
2. Map each component to ontology IDs independently
3. Record the phenotype's `trait_type` as `interaction`/`stratified`/`adjusted`
4. If there's a single best "primary" concept, mark it `skos:closeMatch`; mark modifiers as `skos:relatedMatch`

### Phase 4: Assign Stable Portal IDs

After mappings are complete, assign new numeric IDs:

- Format: `KPN.TRAIT:{NNNNNNN}` (7-digit zero-padded, e.g., `KPN.TRAIT:0000001`)
- Reuse the numeric IDs in the existing versioned registry, keyed by source category and legacy phenotype ID. Append new IDs above the existing maximum; never renumber existing records. For a first-ever registry only, sort by `trait_group` (portal first, then gcat_trait, then rare_v2), then by `display_group`, then alphabetically by `phenotype`
- Keep a registry mapping file (`data/portal_id_registry.tsv`) with columns:
  ```
  portal_id | legacy_trait_group | legacy_phenotype_id | phenotype_name | display_group | trait_type
  ```

---

## Output Data Model (LinkML + SSSOM)

### LinkML Schema (`schema/portal_phenotype.yaml`)

Define a LinkML schema with these classes:

```yaml
id: https://kp.a2f.org/portal-phenotype-model
name: portal-phenotype-model
prefixes:
  KPN.TRAIT: https://broadinstitute.github.io/kpn-data-models/kpn.trait/
  linkml: https://w3id.org/linkml/
  skos: http://www.w3.org/2004/02/skos/core#
  sssom: https://w3id.org/sssom/
  efo: http://www.ebi.ac.uk/efo/
  mondo: http://purl.obolibrary.org/obo/MONDO_
  mesh: http://id.nlm.nih.gov/mesh/
  hp: http://purl.obolibrary.org/obo/HP_
  doid: http://purl.obolibrary.org/obo/DOID_
  ordo: http://www.orpha.net/ORDO/Orphanet_
  chebi: http://purl.obolibrary.org/obo/CHEBI_
  oba: http://purl.obolibrary.org/obo/OBA_
  cmo: http://purl.obolibrary.org/obo/CMO_

classes:
  PortalPhenotype:
    description: >-
      A phenotype tracked in the A2F Knowledge Portal, with a stable numeric ID,
      legacy identifiers, classification, and cross-ontology mappings.
    attributes:
      portal_id:
        range: string
        required: true
        identifier: true
        description: "Stable numeric ID (e.g., KPN.TRAIT:0000001)"
      legacy_id:
        range: string
        required: true
        description: "Original text-based phenotype ID from Phenotypes.tsv"
      legacy_trait_group:
        range: TraitGroupEnum
        required: true
      phenotype_name:
        range: string
        required: true
        description: "Human-readable phenotype label"
      description:
        range: string
        description: "Extended description if available"
      display_group:
        range: string
        description: "Disease area category (e.g., CARDIOVASCULAR)"
      trait_type:
        range: TraitTypeEnum
        required: true
      is_dichotomous:
        range: boolean
        description: "Whether this is a case/control (dichotomous) phenotype"
      component_phenotypes:
        range: PortalPhenotype
        multivalued: true
        description: "For composite/interaction phenotypes, references to the component phenotypes"
      primary_concept:
        range: OntologyMapping
        description: "The single best ontology mapping for this phenotype"
      mappings:
        range: OntologyMapping
        multivalued: true
        inlined_as_list: true
        description: "All cross-ontology mappings"

  OntologyMapping:
    description: >-
      A mapping from a portal phenotype to an external ontology term,
      following SSSOM conventions.
    attributes:
      target_id:
        range: uriorcurie
        required: true
        description: "External ontology ID (e.g., EFO:0000275, MESH:D001281)"
      target_label:
        range: string
      target_ontology:
        range: OntologyEnum
        required: true
      mapping_predicate:
        range: MappingPredicateEnum
        required: true
        description: "SKOS predicate describing the relationship"
      mapping_justification:
        range: MappingJustificationEnum
        description: "How this mapping was determined"
      confidence:
        range: float
        minimum_value: 0.0
        maximum_value: 1.0
        description: "Confidence score (1.0 = manually curated exact match)"
      source:
        range: string
        description: "Which source file or process produced this mapping"

enums:
  TraitGroupEnum:
    permissible_values:
      portal: { description: "Core portal phenotype" }
      gcat_trait: { description: "GWAS Catalog-sourced trait" }
      rare_v2: { description: "Rare disease from Orphanet" }

  TraitTypeEnum:
    permissible_values:
      disease: { description: "A diagnosable disease or condition" }
      measurement: { description: "A quantitative measurement or biomarker" }
      phenotype: { description: "An observable characteristic (not disease or measurement)" }
      rare_disease: { description: "Rare disease from Orphanet registry" }
      interaction: { description: "Gene-environment or trait-trait interaction (e.g., AFxBMI)" }
      stratified: { description: "Trait within a subpopulation (e.g., AlbInT2D)" }
      adjusted: { description: "Trait adjusted for covariates (e.g., ISIadjAgeSexBMI)" }
      subgroup: { description: "Age/sex/ancestry-specific subgroup analysis" }
      composite: { description: "Combined or alternative phenotype definitions (e.g., AD_or_AD_history)" }

  OntologyEnum:
    permissible_values:
      EFO: { description: "Experimental Factor Ontology" }
      MeSH: { description: "Medical Subject Headings" }
      MONDO: { description: "Mondo Disease Ontology" }
      HP: { description: "Human Phenotype Ontology" }
      DOID: { description: "Disease Ontology" }
      Orphanet: { description: "Orphanet Rare Disease Ontology" }
      CHEBI: { description: "Chemical Entities of Biological Interest" }
      OBA: { description: "Ontology of Biological Attributes" }
      CMO: { description: "Clinical Measurement Ontology" }

  MappingPredicateEnum:
    permissible_values:
      skos:exactMatch: { description: "Exact semantic equivalence" }
      skos:closeMatch: { description: "Sufficiently similar to be used interchangeably in some contexts" }
      skos:broadMatch: { description: "Target is broader/more general than the portal phenotype" }
      skos:narrowMatch: { description: "Target is narrower/more specific than the portal phenotype" }
      skos:relatedMatch: { description: "Associative mapping (e.g., component of a composite phenotype)" }

  MappingJustificationEnum:
    permissible_values:
      manual_curation: { description: "Manually curated by a domain expert" }
      lexical_match: { description: "Automated exact or fuzzy text match" }
      cross_reference: { description: "Extracted from ontology cross-references (hasDbXref)" }
      semantic_similarity: { description: "Embedding-based similarity search" }
      gwas_catalog: { description: "Derived from GWAS Catalog MAPPED_TRAIT_URI" }
      inherited: { description: "Inherited from a prior mapping file (portal_to_mesh or AMP)" }
```

### SSSOM Output (`data/portal_phenotype_mappings.sssom.tsv`)

In addition to the LinkML instances, produce a standard SSSOM TSV:

```
# curie_map:
#   KPN.TRAIT: https://broadinstitute.github.io/kpn-data-models/kpn.trait/
#   EFO: http://www.ebi.ac.uk/efo/EFO_
#   MESH: http://id.nlm.nih.gov/mesh/
#   MONDO: http://purl.obolibrary.org/obo/MONDO_
#   HP: http://purl.obolibrary.org/obo/HP_
# mapping_set_id: https://broadinstitute.github.io/kpn-data-models/kpn.trait/mappings
# mapping_set_version: 2026-03-13
subject_id	subject_label	predicate_id	object_id	object_label	mapping_justification	confidence
KPN.TRAIT:0000001	Atrial Fibrillation	skos:exactMatch	EFO:0000275	atrial fibrillation	semapv:ManualMappingCuration	1.0
KPN.TRAIT:0000001	Atrial Fibrillation	skos:exactMatch	MESH:D001281	Atrial Fibrillation	semapv:ManualMappingCuration	1.0
KPN.TRAIT:0000001	Atrial Fibrillation	skos:exactMatch	MONDO:0004981	atrial fibrillation	semapv:LogicalReasoning	0.95
```

---

## Execution Plan (Step-by-Step)

### Step 0: Project Setup
- Create directory structure:
  ```
  portal-data-models/
  ├── CLAUDE.md          (this file)
  ├── raw/               (source data — DO NOT MODIFY)
  ├── schema/            (LinkML schema definitions)
  ├── scripts/           (Python processing scripts)
  ├── data/              (output data files)
  └── reports/           (curation reports, gap analysis)
  ```
- Initialize a `pyproject.toml` with dependencies: `linkml`, `sssom`, `pronto`, `rdflib`, `aiohttp`, `pandas`
- **IMPORTANT**: This is a mounted environment. Do not run `uv`, `pip install`, or activate virtual environments. Write the scripts and ask the user to install any missing dependencies.

### Step 1: Parse and Consolidate Source Data
- Script: `scripts/01_parse_sources.py`
- Read all source files into a unified internal representation
- For each phenotype in `Phenotypes.tsv`, create a record with:
  - `legacy_trait_group`, `legacy_id`, `phenotype_name`, `display_group`
  - Classify `trait_type` based on naming patterns:
    - `rare_v2` → `rare_disease`
    - Portal IDs containing `x[A-Z]` → likely `interaction`
    - Portal IDs containing `adj` → likely `adjusted`
    - Portal IDs containing `In[A-Z]` or `inT2D` → likely `stratified`
    - Portal IDs containing `_or_` → likely `composite`
    - AMP file `complex traits` == `complex` → use as hint
    - AMP file `dichotomous` == 1 → likely `disease`
  - Attach existing MeSH mappings from `portal_to_mesh_curated_collected.tsv`
  - Attach existing EFO mappings from `amp-traits-mapping-portal-phenotypes_06262024.csv`
  - For `gcat_trait` phenotypes, match to GWAS Catalog and extract `MAPPED_TRAIT_URI`
  - For `rare_v2` phenotypes, extract embedded Orphanet IDs
- Output: `data/01_consolidated_phenotypes.json`

### Step 2: Extract Cross-References from EFO OWL
- Script: `scripts/02_parse_efo_xrefs.py`
- Parse `raw/efo.owl` to build a mapping table: EFO_ID ↔ {MeSH, MONDO, HP, DOID, Orphanet, ...}
- Also parse `raw/ORDO_en_4.5.owl` to get Orphanet ↔ {MONDO, HP, ...} mappings
- Output: `data/02_ontology_xref_table.tsv`

### Step 3: Enrich via OLS API
- Script: `scripts/03_ols_bulk_lookup.py`
- For phenotypes still missing key mappings (especially EFO or MONDO), query OLS REST API
- Prioritize: portal phenotypes > gcat_trait > rare_v2
- For each unique MeSH ID, fetch OLS entry and extract cross-references
- For unmapped phenotype names, do text search across EFO/MONDO/HP
- Output: `data/03_ols_enriched_mappings.tsv`

### Step 4: Agent-Assisted Curation
- **This is where you (the agent) apply expert judgment using MCP tools**
- Read `data/03_ols_enriched_mappings.tsv` and identify:
  - Phenotypes with zero mappings
  - Phenotypes with low-confidence mappings
  - Composite phenotypes that need decomposition
- For each, use the ontology-lookup-service MCP tools to search, compare, and decide
- Use `mcp__ontology-lookup-service__searchClasses` with `ontologyId` filters (efo, mondo, hp, mesh)
- Use `mcp__ontology-lookup-service__getSimilarClasses` for fuzzy/embedding-based matching
- Use `mcp__ontology-lookup-service__getAncestors` to verify hierarchy relationships (is the match too broad? too narrow?)
- Record decisions in `data/04_curated_mappings.tsv` with `mapping_justification` = `manual_curation`
- Work in batches. For efficiency, use subagents to curate independent phenotype groups in parallel (by `display_group`).

### Step 5: Assign Stable IDs and Generate Final Output
- Script: `scripts/05_generate_output.py`
- Assign `KPN.TRAIT:NNNNNNN` IDs
- Generate:
  - `schema/portal_phenotype.yaml` — the LinkML schema (use the template above)
  - `data/portal_phenotype_registry.tsv` — the ID registry
  - `data/portal_phenotype_mappings.sssom.tsv` — SSSOM mapping set
  - `data/portal_phenotypes.yaml` — full LinkML instance data
- Validate with `linkml-validate` and `sssom validate` (ask user to run)

### Step 6: Quality Report
- Script: `scripts/06_quality_report.py`
- Generate `reports/mapping_coverage.md`:
  - Mapping coverage by ontology (% of phenotypes with EFO, MeSH, MONDO, HP mapping)
  - Coverage by trait_group and display_group
  - List of phenotypes with no mappings
  - List of phenotypes with only low-confidence mappings
  - Distribution of mapping predicates (how many exactMatch vs broadMatch, etc.)

---

## Key Heuristics for Trait Type Classification

Use these patterns on the `legacy_id` (phenotype column) from `Phenotypes.tsv`:

| Pattern | Example | Trait Type |
|---|---|---|
| `rare_v2` trait group | `HermanskyPudlak_syndrome_Orphanet_79430` | `rare_disease` |
| Contains `x` followed by uppercase | `AFxBMI`, `AFxSEX`, `AFxAGE` | `interaction` |
| Contains `int` or `joint` or `main` suffix | `SmokingT2Dint`, `SmokingFGjoint` | `interaction` |
| Contains `In` followed by uppercase (in-context) | `AlbInT2D`, `AnyCVDinT2D` | `stratified` |
| Contains `v` between words (versus) | `AllDKDvControl_DM` | `stratified` |
| Contains `adj` | `ISIadjAgeSexBMI`, `CKDextremesadjHbA1cBMI` | `adjusted` |
| Contains `_or_` | `AD_or_AD_history` | `composite` |
| Time-specific suffix | `BMI1yr`, `BMI6mons`, `BMI3yrs` | `subgroup` |
| Age-specific suffix | `AFxAGEo65`, `AFxAGEy65` | `subgroup` |
| AMP `dichotomous` == 1 and simple | `AF`, `AD`, `T2D` | `disease` |
| AMP `dichotomous` == 0 and simple | `BMI`, `ALBUMIN` | `measurement` |
| `gcat_trait` with `_measurement` suffix | `gcat_trait_cerebellin4_measurement` | `measurement` |
| Default for `gcat_trait` | `gcat_trait_Moyamoya_disease` | Infer from name — diseases end in "disease"/"syndrome"/"disorder" |

These are heuristics, not absolute rules. The `phenotype_name` (human-readable label) and AMP file metadata should be used to validate and override.

---

## MCP Tool Usage Guide

The agent has access to an **ontology-lookup-service** MCP server. Key tools:

### Searching
```
mcp__ontology-lookup-service__search(query="atrial fibrillation")
```
- Searches across ALL ontologies in OLS. Returns IDs in format `ontologyid+entityIri`.

```
mcp__ontology-lookup-service__searchClasses(query="atrial fibrillation", ontologyId="efo")
```
- Searches within a specific ontology. Returns richer results with ancestors, parents, definitions.
- Use `ontologyId` values: `efo`, `mondo`, `hp`, `mesh`, `doid`, `ordo`

### Fetching Details
```
mcp__ontology-lookup-service__fetch(id="efo+http://www.ebi.ac.uk/efo/EFO_0000275")
```
- Fetch full entity details. The `id` must be in format `ontologyid+entityIri` (as returned by search).

### Embedding-Based Similarity
```
mcp__ontology-lookup-service__listEmbeddingModels()  # CALL THIS FIRST
mcp__ontology-lookup-service__searchClassesWithEmbeddingModel(query="body mass index", model="<model_name>", ontologyId="efo")
mcp__ontology-lookup-service__getSimilarClasses(classIri="http://www.ebi.ac.uk/efo/EFO_0000275", model="<model_name>")
```
- For fuzzy matching when exact text search fails.
- Only models with `can_embed=true` can be used with `searchClassesWithEmbeddingModel`.
- Any model works with `getSimilarClasses` (uses pre-computed embeddings).

### Hierarchy Navigation
```
mcp__ontology-lookup-service__getAncestors(ontologyId="efo", classIri="http://www.ebi.ac.uk/efo/EFO_0000275")
mcp__ontology-lookup-service__getDescendants(ontologyId="efo", classIri="http://www.ebi.ac.uk/efo/EFO_0000275")
```
- Use to verify `broadMatch` vs `exactMatch` — if the portal phenotype is a child of the OLS result, the match is `narrowMatch`; if parent, `broadMatch`.

---

## Environment Notes

- **Mounted environment**: Do NOT run `uv`, `pip`, `python`, or activate virtual environments. Write scripts and tell the user what dependencies to install and what commands to run.
- Python 3.9+ target.
- Prefer `pandas` for tabular data, `rdflib`/`pronto` for OWL parsing, `linkml-runtime` for schema validation.
- The `efo.owl` file is 330MB — parsing it will take time. Consider extracting cross-references once and caching to a TSV.

---

## Quality Standards

- Every phenotype in `Phenotypes.tsv` MUST have a `KPN.TRAIT:NNNNNNN` ID and a `trait_type` classification
- Target: >90% of `portal` phenotypes mapped to at least one of {EFO, MONDO, MeSH}
- Target: >95% of `rare_v2` phenotypes mapped to Orphanet (they already have IDs embedded)
- Target: >80% of `gcat_trait` phenotypes mapped to EFO (via GWAS Catalog)
- Every mapping MUST have a `mapping_predicate` and `mapping_justification`
- No mapping should have `confidence` > 0.9 unless it's been validated (by cross-reference, exact lexical match, or manual curation)
