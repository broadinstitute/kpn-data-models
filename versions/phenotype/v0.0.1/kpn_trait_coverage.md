# Portal Phenotype Mapping Coverage Report — v0.0.1

## Overall Summary

- **Total phenotypes**: 8402
- **Total mappings**: 24050
- **Phenotypes with any mapping**: 8402 (100.0%)
- **Phenotypes with NO mapping**: 0 (0.0%)

## Coverage by Ontology

| Ontology | Mapped | % of Total |
|----------|--------|------------|
| EFO | 5548 | 66.0% |
| MESH | 3153 | 37.5% |
| MONDO | 2151 | 25.6% |
| HP | 508 | 6.0% |
| DOID | 1080 | 12.9% |
| ORPHANET | 3092 | 36.8% |
| CHEBI | 31 | 0.4% |
| OBA | 616 | 7.3% |
| CMO | 14 | 0.2% |
| ICD10CM | 548 | 6.5% |

## Coverage by Trait Group

| Trait Group | Total | EFO | MESH | MONDO | ORPHANET | Any | None |
|-------------|-------|-----|------|-------|----------|-----|------|
| portal | 1439 | 1439 (100%) | 944 (66%) | 232 (16%) | 54 (4%) | 1439 (100%) | 0 (0%) |
| gcat_trait | 4027 | 4027 (100%) | 1208 (30%) | 396 (10%) | 102 (3%) | 4027 (100%) | 0 (0%) |
| rare_v2 | 2936 | 82 (3%) | 1001 (34%) | 1523 (52%) | 2936 (100%) | 2936 (100%) | 0 (0%) |

## Quality Targets

| Target | Actual | Status |
|--------|--------|--------|
| >90% portal → EFO/MONDO/MESH | 100.0% (1439/1439) | PASS |
| >95% rare_v2 → ORPHANET | 100.0% (2936/2936) | PASS |
| >80% gcat_trait → EFO | 100.0% (4027/4027) | PASS |

## Predicate Distribution

| Predicate | Count | % |
|-----------|-------|---|
| skos:exactMatch | 20425 | 84.9% |
| skos:broadMatch | 2087 | 8.7% |
| oboInOwl:hasDbXref | 596 | 2.5% |
| skos:closeMatch | 589 | 2.4% |
| skos:relatedMatch | 353 | 1.5% |

## Trait Type Distribution

| Trait Type | Count | % |
|------------|-------|---|
| measurement | 3279 | 39.0% |
| rare_disease | 2936 | 34.9% |
| phenotype | 1652 | 19.7% |
| disease | 292 | 3.5% |
| adjusted | 102 | 1.2% |
| stratified | 102 | 1.2% |
| interaction | 17 | 0.2% |
| subgroup | 14 | 0.2% |
| composite | 8 | 0.1% |