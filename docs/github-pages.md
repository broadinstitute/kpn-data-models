# Trait browser and releases

Traits is the KPN object category, organized under `schemas/trait/`, `scripts/trait/`, `raw/trait/`, `data/trait/`, and `versions/trait/`. The schema file is `schemas/trait/kpn_trait.yaml`. Existing schema classes, data fields (including `phenotypes` and `phenotype_name`), type values such as `phenotype`, and original source filenames retain their names.

Every trait has a stable page:

`https://broadinstitute.github.io/kpn-data-models/kpn.trait/0000001/`

The seven-digit suffix is the numeric part of `KPN.TRAIT:0000001`. The page shows the trait name, description, legacy and PIGEAN IDs, classification, primary mapping, every ontology mapping, relationship, confidence, source, and notes. JSON is available at the same URL followed by `record.json`. Missing identifiers show a useful 404 page; directory URLs also work without the trailing slash on GitHub Pages.

The searchable catalogue is at `/kpn-data-models/` and `/kpn-data-models/kpn.trait/`. Search includes trait names, legacy IDs, PIGEAN IDs, KPN.TRAIT IDs, mapped ontology identifiers, and mapped labels. Results can be filtered by source collection and trait group. Each trait page can filter mappings by ontology. Trait pages contain all data in HTML and work without JavaScript; catalogue search uses JavaScript. Complete YAML, flat TSV, SSSOM, registry, and coverage downloads are served alongside the pages.

The five release files use a consistent `kpn_trait_` prefix:

- `kpn_trait_collection.yaml` — complete trait collection.
- `kpn_trait_flat.tsv` — one row per mapping with trait details.
- `kpn_trait_registry.tsv` — stable IDs and trait names.
- `kpn_trait_mappings.sssom.tsv` — SSSOM mapping set.
- `kpn_trait_coverage.md` — coverage report.

These names are used by the generator, release assets, and the site's `/downloads/` links.

## Publishing a release

1. Merge these changes into `main` and let **Validate data and site** pass.
2. In repository **Settings → Pages → Build and deployment**, select **GitHub Actions** as the source. See [GitHub's custom workflow instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
3. Publish a GitHub release tagged `v0.0.2` from the commit containing the Traits layout and versioned exports. A Git tag alone does not trigger deployment.
4. **Attach trait release files** uploads the five versioned exports as release assets. After that workflow succeeds, **Publish latest release to Pages** runs from `main`, resolves GitHub's latest stable published release, checks out that tag, and builds from `versions/trait/<tag>/`. Running in the default-branch context satisfies the Pages environment's `main` deployment restriction; data still comes exclusively from the released tag.
5. Open the Pages URL from the deployment job. To redeploy after a site-only change, run **Publish latest release to Pages** manually from Actions.

The latest-release endpoint excludes drafts and prereleases. Every deployment resolves the latest stable release, including when an older release triggers the asset workflow. Editing release metadata alone does not trigger deployment; use the manual workflow when needed. There is deliberately no fallback to unreleased `main` data. If no stable release exists, the deployment fails with the GitHub API error and the existing site is untouched. `release.json` and every page identify the exact release used. Do not move published tags or edit versioned exports after release; make a new version instead.

The Pages build uses the renderer and schema on `main`, with trait data from the release tag. CI validates the frozen v0.0.1 data baseline, schema, generator, and site behavior. The builder also validates the released collection against the schema before rendering. Release assets come directly from the same checked-in snapshot. This avoids browser API rate limits and cross-origin asset fetches.

## Local preview

```bash
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python scripts/site/build.py \
  --data-dir versions/trait/v0.0.2 --release v0.0.2
python3 -m http.server 8000 --directory site/_build
```

Open `http://localhost:8000/`. Build output must be a new or empty directory so pages from different releases cannot mix; use `--output /tmp/kpn-preview-new` for another build. The default output `site/_build/` is ignored by Git. `--base-path /kpn-data-models` supports project Pages; the deployment workflow obtains the path from `actions/configure-pages`. For that local layout, build to a parent directory containing `kpn-data-models/` and serve the parent.

## Namespace migration and regression checks

```bash
./scripts/trait/v0.0.1/generate.sh \
  --from-release versions/trait/v0.0.1
uv run python -m unittest discover -s tests -v
```

The offline rebuild reads YAML for mappings and provenance and the flat TSV for the original flags. It preserves the release's SSSOM date. The existing registry supplies ID numbers; new traits receive numbers above the current maximum. Missing registered traits, duplicate identities, and duplicate ID numbers are errors. `04_generate_output.py --registry <path>` allows an explicit prior registry for later versions.

The 1,439 core traits use `KPN` as their source collection, replacing `portal`. The parser and generator accept the legacy category and normalize both input records and registry keys before matching IDs. The other source collections (`gcat_trait`, `rare_v2`) and mapping provenance filenames are unchanged. The catalogue also accepts old `?source=portal` links and updates them to `?source=KPN`.

`tests/fixtures/v0.0.1-baseline.json` records content hashes from commit `dcdb13b9ed8e39007678d8b488dc3a7197f2096b`, before the prefix migration. Tests normalize only the identifier prefix, the core source category rename and public Traits wording in coverage-report labels, and SSSOM comment metadata. Every numeric ID, other trait field, mapping, primary selection, row order, and coverage statistic must remain identical. Separate checks enforce the new namespace and source categories, declared CURIE prefixes, and byte-for-byte offline regeneration. Do not refresh that fixture to hide a regression; intentional mapping changes belong in the next version.

The fixture keys use the current `kpn_trait_` filenames; the original content hashes were preserved through the filename migration.

Schema declarations now cover the existing PIGEAN ID field, OMIM/GO/NCIT/PATO mappings, and `oboInOwl:hasDbXref`. These fixes describe the existing data; no mappings were changed.

## Other object types

The site reserves a separate namespace path per object category. `scripts/site/build.py` currently builds Traits at `kpn.trait/` from trait releases and uses shared page framing and assets. Future objects can add a loader and renderer under their own path (for example `kpn.gene/`) without changing trait URLs or introducing a client-side router. Traits is the only public object category implemented today.
