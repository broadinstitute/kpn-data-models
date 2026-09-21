"""Guard the pre-release data, ID stability, and offline regeneration contract."""
import copy
import csv
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / 'versions/phenotype/v0.0.1'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load_module('generator', 'scripts/phenotype/v0.0.1/04_generate_output.py')


def normalized_content(path):
    """Ignore ONLY the identifier namespace and SSSOM comment metadata."""
    if path.suffix == '.yaml':
        value = yaml.load(path.read_text(), Loader=yaml.CSafeLoader)
        for row in value['phenotypes']:
            row['portal_id'] = row['portal_id'].split(':')[1]
    elif path.suffix == '.tsv':
        with path.open(newline='') as f:
            value = list(csv.DictReader((line for line in f if not line.startswith('#')), delimiter='\t'))
        field = 'subject_id' if '.sssom.' in path.name else 'portal_id'
        for row in value:
            row[field] = row[field].split(':')[1]
    else:
        value = path.read_text()
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


class ReleaseRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((ROOT / 'tests/fixtures/v0.0.1-baseline.json').read_text())
        cls.phenotypes = yaml.load((RELEASE / 'kpn_trait_collection.yaml').read_text(), Loader=yaml.CSafeLoader)['phenotypes']

    def test_all_release_content_matches_pre_migration_baseline(self):
        # Includes every label, number, mapping, primary selection, predicate,
        # confidence, provenance, note, classification, flag, and output row.
        for filename, digest in self.baseline['sha256'].items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256(normalized_content(RELEASE / filename)).hexdigest(), digest)

    def test_namespace_counts_and_cross_export_identity(self):
        expected = {p['portal_id'] for p in self.phenotypes}
        self.assertEqual(len(expected), self.baseline['phenotypes'])
        self.assertEqual(len(self.phenotypes), len(expected))
        self.assertTrue(all(re.fullmatch(r'KPN\.TRAIT:[0-9]{7}', pid) for pid in expected))
        self.assertEqual(sum(len(p.get('mappings', [])) for p in self.phenotypes), self.baseline['mappings'])
        for filename, field in [('kpn_trait_registry.tsv', 'portal_id'), ('kpn_trait_flat.tsv', 'portal_id'), ('kpn_trait_mappings.sssom.tsv', 'subject_id')]:
            with (RELEASE / filename).open(newline='') as f:
                ids = {r[field] for r in csv.DictReader((line for line in f if not line.startswith('#')), delimiter='\t')}
            self.assertEqual(ids, expected)
        text = (RELEASE / 'kpn_trait_mappings.sssom.tsv').read_text()
        self.assertIn(f'#   KPN.TRAIT: {generator.TRAIT_BASE_URL}', text)
        self.assertNotIn('PORTAL:', text)
        metadata = yaml.safe_load('\n'.join(line[2:] for line in text.splitlines() if line.startswith('# ')))
        with (RELEASE / 'kpn_trait_mappings.sssom.tsv').open() as f:
            for row in csv.DictReader((line for line in f if not line.startswith('#')), delimiter='\t'):
                for field in ('subject_id', 'object_id', 'predicate_id', 'mapping_justification'):
                    self.assertIn(row[field].split(':')[0], metadata['curie_map'])

    def test_schema_accepts_collection_and_rejects_old_prefix(self):
        from linkml.generators.jsonschemagen import JsonSchemaGenerator
        from jsonschema import Draft7Validator
        schema = json.loads(JsonSchemaGenerator(str(ROOT / 'schemas/phenotype/portal_phenotype.yaml')).serialize())
        validator = Draft7Validator(schema)
        validator.validate({'phenotypes': self.phenotypes})
        bad = copy.deepcopy(self.phenotypes[0])
        bad['portal_id'] = 'PORTAL:0000001'
        self.assertFalse(validator.is_valid({'phenotypes': [bad]}))
        bad['portal_id'] = 'KPNxTRAIT:0000001'
        self.assertFalse(validator.is_valid({'phenotypes': [bad]}))

    def test_offline_regeneration_preserves_every_export(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            subprocess.run([
                sys.executable, str(ROOT / 'scripts/phenotype/v0.0.1/04_generate_output.py'),
                '--from-release', str(RELEASE), '--output-dir', str(dest),
            ], check=True, capture_output=True, text=True)
            self.assertEqual({path.name for path in dest.iterdir()}, {
                'kpn_trait_registry.tsv', 'kpn_trait_mappings.sssom.tsv',
                'kpn_trait_collection.yaml', 'kpn_trait_flat.tsv',
            })
            for path in dest.iterdir():
                self.assertEqual(path.read_bytes(), (RELEASE / path.name).read_bytes(), path.name)


class StableIdTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.registry = Path(self.directory.name) / 'registry.tsv'
        self.registry.write_text('portal_id\tgwas_source_category\tlegacy_phenotype_id\nPORTAL:0000042\tportal\told\nKPN.TRAIT:0000999\tportal\tother\n')
        self.records = [{'gwas_source_category': 'portal', 'phenotype': 'other', 'legacy_trait_group': 'z'},
                        {'gwas_source_category': 'portal', 'phenotype': 'old', 'legacy_trait_group': 'renamed'}]

    def test_preserves_numbers_when_sort_order_changes_and_appends_new_ids(self):
        self.records.append({'gwas_source_category': 'portal', 'phenotype': 'aaa', 'legacy_trait_group': 'a'})
        records = generator.assign_portal_ids(self.records, self.registry)
        self.assertEqual({r['phenotype']: r['portal_id'] for r in records}, {'old': 'KPN.TRAIT:0000042', 'other': 'KPN.TRAIT:0000999', 'aaa': 'KPN.TRAIT:0001000'})

    def test_rejects_missing_registered_traits(self):
        with self.assertRaisesRegex(ValueError, 'drops 1'):
            generator.assign_portal_ids(self.records[:1], self.registry)

    def test_rejects_duplicate_input(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate phenotype'):
            generator.assign_portal_ids(self.records + self.records, self.registry)

    def test_rejects_duplicate_registry_ids(self):
        self.registry.write_text(self.registry.read_text().replace('KPN.TRAIT:0000999', 'PORTAL:0000042'))
        with self.assertRaisesRegex(ValueError, 'Duplicate registry'):
            generator.assign_portal_ids(self.records, self.registry)

    def test_explicit_missing_input_does_not_silently_fall_back(self):
        with self.assertRaises(FileNotFoundError):
            generator.load_input(Path(self.directory.name) / 'missing.json')


if __name__ == '__main__':
    unittest.main()
