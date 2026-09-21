#!/usr/bin/env python3
"""Build static object pages from one released phenotype collection.

No browser API calls, SPA redirects, or external frontend dependencies required.
Each object namespace owns its renderer; future objects can add another builder.
"""
import argparse
import csv
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = (
    'kpn_trait_collection.yaml', 'kpn_trait_flat.tsv',
    'kpn_trait_registry.tsv', 'kpn_trait_mappings.sssom.tsv',
    'kpn_trait_coverage.md',
)
ONTOLOGY_URLS = {
    'EFO': 'http://www.ebi.ac.uk/efo/EFO_',
    'MESH': 'https://id.nlm.nih.gov/mesh/',
    'ORPHANET': 'https://www.orpha.net/ORDO/Orphanet_',
    'ICD10CM': 'https://purl.bioontology.org/ontology/ICD10CM/',
    'OMIM': 'https://omim.org/entry/',
    **{key: f'https://purl.obolibrary.org/obo/{key}_'
       for key in ('MONDO', 'HP', 'DOID', 'CHEBI', 'OBA', 'CMO', 'GO', 'NCIT', 'PATO')},
}


def esc(value):
    return html.escape(str(value), quote=True)


def ontology_link(identifier):
    prefix, _, number = identifier.partition(':')
    base = ONTOLOGY_URLS.get(prefix)
    if not base:
        return f'<span class="identifier">{esc(identifier)}</span>'
    return f'<a class="identifier" href="{esc(base + quote(number, safe=""))}">{esc(identifier)}</a>'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def render_page(title, body, base_path, release, repository, script=''):
    base = base_path.rstrip('/')
    release_url = f'https://github.com/{repository}/releases/tag/{quote(release, safe="")}'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} | KPN data</title><meta name="description" content="Knowledge Portal Network trait identifiers, names, and ontology mappings.">
<link rel="stylesheet" href="{esc(base)}/assets/style.css">
{f'<script src="{esc(base)}/assets/{script}" defer></script>' if script else ''}</head>
<body><a class="skip" href="#main">Skip to content</a>
<header><nav aria-label="Main"><a class="brand" href="{esc(base)}/" aria-label="KPN home"><img src="{esc(base)}/assets/kpn-logo.png" alt="KPN" width="360" height="190"></a>
<div class="nav-links"><a href="{esc(base)}/kpn.trait/">Traits</a><a href="https://github.com/{esc(repository)}">Repository</a></div>
<a class="release" href="{esc(release_url)}">Release {esc(release)}</a></nav></header>
<main id="main">{body}</main>
<footer>Knowledge Portal Network <span>Data from <a href="{esc(release_url)}">{esc(release)}</a> · <a href="{esc(base)}/downloads/kpn_trait_coverage.md">Coverage report</a></span></footer>
</body></html>'''


def render_trait(record, flat, base):
    identifier = record['portal_id']
    number = identifier.split(':')[1]
    mappings = record.get('mappings', [])
    primary = record.get('primary_mapping')
    fields = [
        ('Legacy ID', record['legacy_id']), ('PIGEAN ID', record.get('pigean_id')),
        ('Source collection', record['gwas_source_category']),
        ('Trait type', record['trait_type']), ('Trait group', record['trait_group']),
        ('Legacy group', record.get('legacy_trait_group')),
        ('Dichotomous', str(record['is_dichotomous']).lower() if 'is_dichotomous' in record else None),
        ('Complex trait', flat.get('is_complex')),
    ]
    metadata = ''.join(f'<dt>{label}</dt><dd>{esc(value)}</dd>' for label, value in fields if value is not None and value != '')
    primary_html = ''
    if primary:
        primary_html = f'''<section class="primary"><h2>Primary mapping</h2>
        {ontology_link(primary['target_id'])}<p>{esc(primary.get('target_label') or 'Label not provided')}</p>
        <span>{esc(primary['mapping_predicate'])} · Confidence {esc(primary.get('confidence', 'Not provided'))}</span></section>'''
    rows = []
    for mapping in mappings:
        notes = f'<p class="notes">{esc(mapping["notes"])}</p>' if mapping.get('notes') else ''
        rows.append(f'''<tr data-ontology="{esc(mapping['target_ontology'])}">
<td>{ontology_link(mapping['target_id'])}<div class="term-label">{esc(mapping.get('target_label') or 'Label not provided')}</div></td>
<td><span class="predicate">{esc(mapping['mapping_predicate'])}</span></td>
<td class="confidence">{esc(mapping.get('confidence', 'Not provided'))}</td>
<td>{esc(mapping.get('mapping_justification') or 'Not provided')}<div class="provenance">{esc(mapping.get('source') or 'Source not provided')}</div>{notes}</td></tr>''')
    options = ''.join(f'<option>{esc(ontology)}</option>' for ontology in sorted({m['target_ontology'] for m in mappings}))
    description = f'<p class="description">{esc(record["description"])}</p>' if record.get('description') and record['description'] != record['phenotype_name'] else ''
    return f'''<a class="back" href="{esc(base)}/kpn.trait/">All traits</a>
<div class="trait-heading"><div><p class="identifier object-id">{esc(identifier)}</p><h1>{esc(record['phenotype_name'])}</h1>{description}</div>
<a class="download" href="{esc(base)}/kpn.trait/{number}/record.json" download>Download record JSON</a></div>
<div class="trait-layout"><aside aria-label="Trait details"><h2>Trait details</h2><dl>{metadata}</dl>{primary_html}</aside>
<section class="mapping-section"><div class="section-heading"><h2>Ontology mappings <span class="count">{len(mappings)}</span></h2>
<label class="js-only">Ontology <select id="ontology"><option value="">All ontologies</option>{options}</select></label></div>
<p class="hint">Relationships describe this trait relative to each mapped term.</p>
<div class="table-scroll"><table class="mappings"><caption class="sr-only">All mappings for {esc(identifier)}</caption><thead><tr><th scope="col">Term</th><th scope="col">Relationship</th><th scope="col">Confidence</th><th scope="col">Evidence and source</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p id="mapping-status" class="hint" role="status">{len(mappings)} mappings</p>
{'' if mappings else '<p>No ontology mappings in this release.</p>'}
</section></div>'''


def result_row(record, base):
    number = record['portal_id'].split(':')[1]
    return f'''<tr><td><a href="{esc(base)}/kpn.trait/{number}/">{esc(record['phenotype_name'])}</a>
<div class="identifier">{esc(record['portal_id'])}</div></td><td>{esc(record['trait_group'])}</td>
<td>{esc(record['gwas_source_category'])}</td><td>{len(record.get('mappings', []))}</td></tr>'''


def build_site(data_dir, output, release, repository, base_path=''):
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', release):
        raise ValueError('Release must be a version tag, e.g. v0.0.1')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Repository must be owner/name')
    if base_path and (not base_path.startswith('/') or urlsplit(base_path).netloc or '..' in base_path or '?' in base_path or '#' in base_path):
        raise ValueError('Base path must be an absolute URL path')
    base = base_path.rstrip('/')
    # Load and validate before producing any output. Never clean a caller's directory.
    if output.exists() and any(output.iterdir()):
        raise ValueError(f'Output directory must be empty: {output}')
    for name in EXPORTS:
        if not (data_dir / name).is_file():
            raise ValueError(f'Missing release export: {name}')
    with (data_dir / EXPORTS[0]).open() as f:
        collection = yaml.load(f, Loader=yaml.CSafeLoader)
    records = collection['phenotypes']
    ids = [r['portal_id'] for r in records]
    if not ids or len(ids) != len(set(ids)) or any(not re.fullmatch(r'KPN\.TRAIT:[0-9]{7}', value) or value.endswith(':0000000') for value in ids):
        raise ValueError('Expected unique, nonzero KPN.TRAIT identifiers')
    from jsonschema import Draft7Validator
    from linkml.generators.jsonschemagen import JsonSchemaGenerator
    schema = json.loads(JsonSchemaGenerator(str(ROOT / 'schemas/trait/kpn_trait.yaml')).serialize())
    Draft7Validator(schema).validate(collection)
    flat = {}
    with (data_dir / 'kpn_trait_flat.tsv').open(newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            flat.setdefault(row['portal_id'], row)
    if set(flat) != set(ids):
        raise ValueError('YAML and flat TSV phenotype IDs disagree')
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'site' / 'assets', output / 'assets')
    shutil.copyfile(ROOT / 'kpn-logo.png', output / 'assets' / 'kpn-logo.png')
    downloads = output / 'downloads'
    downloads.mkdir()
    for name in EXPORTS:
        shutil.copyfile(data_dir / name, downloads / name)
    index = []
    for record in records:
        number = record['portal_id'].split(':')[1]
        directory = output / 'kpn.trait' / number
        body = render_trait(record, flat[record['portal_id']], base)
        write(directory / 'index.html', render_page(record['phenotype_name'], body, base, release, repository, 'trait.js'))
        write(directory / 'record.json', json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        index.append({
            'id': record['portal_id'], 'name': record['phenotype_name'],
            'group': record['trait_group'], 'source': record['gwas_source_category'],
            'count': len(record.get('mappings', [])),
            'search': ' '.join(str(record.get(key, '')) for key in ('portal_id', 'legacy_id', 'phenotype_name', 'description', 'pigean_id')) + ' ' +
                ' '.join(f"{m['target_id']} {m.get('target_label', '')}" for m in record.get('mappings', [])),
        })
    options = ''.join(f'<option>{esc(group)}</option>' for group in sorted({r['trait_group'] for r in records}))
    total_mappings = sum(r['count'] for r in index)
    downloads_html = ''.join(f'<a href="{esc(base)}/downloads/{name}">{label}</a>' for name, label in zip(EXPORTS, ['YAML', 'Flat TSV', 'ID registry', 'SSSOM', 'Coverage report']))
    body = f'''<div class="catalog-heading"><h1>Traits</h1><p>Find a trait. Follow its connections.</p>
<p class="hint">{len(records):,} traits and {total_mappings:,} ontology mappings in {esc(release)}.</p></div>
<section aria-label="Find traits" id="catalog" data-index="{esc(base)}/kpn.trait/index.json" data-base="{esc(base)}">
<div class="filters js-only"><label class="search-label">Search names, IDs, or mapped terms<input type="search" id="search" placeholder="Try atrial fibrillation, KPN.TRAIT:0000001, or EFO:0000275" autocomplete="off"></label>
<label>Trait group<select id="group"><option value="">All groups</option>{options}</select></label>
<label>Source<select id="source"><option value="">All sources</option><option>KPN</option><option>gcat_trait</option><option>rare_v2</option></select></label></div>
<p id="result-status" role="status" class="hint">Showing the first {min(50, len(records))} of {len(records):,} traits.</p>
<div class="table-scroll"><table class="results"><caption class="sr-only">Trait search results</caption><thead><tr><th scope="col">Trait</th><th scope="col">Trait group</th><th scope="col">Source</th><th scope="col">Mappings</th></tr></thead><tbody id="results">{''.join(result_row(r, base) for r in records[:50])}</tbody></table></div>
<div class="pagination js-only"><button id="previous" disabled>Previous</button><span id="page-number"></span><button id="next" disabled>Next</button></div>
<noscript><p>Enable JavaScript to search all traits, or download the full registry below. Individual trait pages work without JavaScript.</p></noscript></section>
<section class="downloads"><h2>Release downloads</h2><p>Complete data files for {esc(release)}.</p><div>{downloads_html}</div></section>'''
    catalogue = render_page('Traits', body, base, release, repository, 'catalog.js')
    write(output / 'index.html', catalogue)
    write(output / 'kpn.trait' / 'index.html', catalogue)
    write(output / 'kpn.trait' / 'mappings' / 'index.html', render_page('Mapping set', f'<h1>Trait mapping set</h1><p>{total_mappings:,} mappings from {esc(release)}.</p><div class="downloads">{downloads_html}</div>', base, release, repository))
    write(output / 'kpn.trait' / 'index.json', json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    write(output / 'release.json', json.dumps({'release': release, 'repository': repository, 'phenotypes': len(records), 'mappings': total_mappings}, indent=2) + '\n')
    write(output / '404.html', render_page('Page not found', f'<h1>Page not found</h1><p>This identifier is not in {esc(release)}. Check the seven-digit ID or <a href="{esc(base)}/">search the trait registry</a>.</p>', base, release, repository))
    write(output / '.nojekyll', '')
    print(f'Built {len(records):,} trait pages with {total_mappings:,} mappings in {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'site' / '_build')
    parser.add_argument('--release', required=True)
    parser.add_argument('--repository', default='broadinstitute/kpn-data-models')
    parser.add_argument('--base-path', default='')
    args = parser.parse_args()
    build_site(args.data_dir, args.output, args.release, args.repository, args.base_path)


if __name__ == '__main__':
    main()
