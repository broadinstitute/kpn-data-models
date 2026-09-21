import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from test_release import ROOT, RELEASE, load_module

site = load_module('site_builder', 'scripts/site/build.py')


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = yaml.load((RELEASE / 'portal_phenotypes.yaml').read_text(), Loader=yaml.CSafeLoader)
        cls.record = data['phenotypes'][0]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.record = copy.deepcopy(self.record)
        self.record['phenotype_name'] = 'Trait <script>alert("unsafe")</script> & name'
        self.record['mappings'][0]['notes'] = 'Review <b>this</b>'
        (self.data / 'portal_phenotypes.yaml').write_text(yaml.safe_dump({'phenotypes': [self.record]}))
        for name in site.EXPORTS[1:]:
            (self.data / name).write_text('portal_id\tis_complex\nKPN.TRAIT:0000001\tfalse\n')
        self.output = self.root / 'public'

    def build(self, base='/kpn-data-models'):
        site.build_site(self.data, self.output, 'v0.0.1', 'broadinstitute/kpn-data-models', base)

    def test_direct_pages_complete_record_provenance_and_escaping(self):
        self.build()
        page = (self.output / 'kpn.trait/0000001/index.html').read_text()
        self.assertNotIn('<script>alert', page)
        self.assertIn('&lt;script&gt;alert', page)
        self.assertIn('Review &lt;b&gt;this&lt;/b&gt;', page)
        self.assertIn('KPN.TRAIT:0000001', page)
        self.assertIn('skos:exactMatch', page)
        self.assertIn('portal_to_mesh_curated_collected.tsv', page)
        self.assertIn('/kpn-data-models/assets/style.css', page)
        self.assertIn('/releases/tag/v0.0.1', page)
        self.assertEqual(json.loads((self.output / 'kpn.trait/0000001/record.json').read_text()), self.record)
        self.assertTrue((self.output / '404.html').exists())
        self.assertTrue((self.output / '.nojekyll').exists())
        index = json.loads((self.output / 'kpn.trait/index.json').read_text())
        self.assertIn('MESH:D011304', index[0]['search'])
        self.assertIn('Presbycusis', index[0]['search'])
        for name in site.EXPORTS:
            self.assertEqual((self.output / 'downloads' / name).read_bytes(), (self.data / name).read_bytes())

    def test_root_path_deployment(self):
        self.build('')
        page = (self.output / 'index.html').read_text()
        self.assertIn('href="/assets/style.css"', page)
        self.assertIn('href="/kpn.trait/0000001/"', page)

    def test_refuses_to_mix_releases_in_existing_output(self):
        self.build()
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.build()

    def test_rejects_unmigrated_release(self):
        p = self.data / 'portal_phenotypes.yaml'
        p.write_text(p.read_text().replace('KPN.TRAIT:', 'PORTAL:'))
        with self.assertRaisesRegex(ValueError, 'KPN.TRAIT'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_inconsistent_release(self):
        (self.data / 'portal_phenotypes_flat.tsv').write_text('portal_id\tis_complex\nKPN.TRAIT:0000002\tfalse\n')
        with self.assertRaisesRegex(ValueError, 'disagree'):
            self.build()

    def test_rejects_path_traversal(self):
        with self.assertRaisesRegex(ValueError, 'Base path'):
            self.build('/../other')


if __name__ == '__main__':
    unittest.main()
