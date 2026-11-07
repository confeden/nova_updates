import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import collector


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.proxy = dict(type='vless', name='upstream', server='example.com', port=443, uuid='test')
        self.key = collector.identity(self.proxy)
        self.registry = dict(version=1, next_number=1, entries={})
        self.now = datetime(2026, 11, 7, tzinfo=timezone.utc)

    def test_returning_profile_keeps_number_and_first_date(self):
        candidates = {self.key: self.proxy}
        first = collector.admit(self.registry, candidates, {self.key: dict(ok=True)}, self.now)
        self.assertEqual(first[0]['name'], 'VLESS_#1_2026nov7')
        self.assertEqual(collector.admit(self.registry, candidates, {self.key: dict(ok=False)}, self.now), [])
        renamed = dict(self.proxy, name='new upstream remarks')
        self.assertEqual(collector.identity(renamed), self.key)
        result = collector.admit(self.registry, {self.key: renamed}, {self.key: dict(ok=True)},
                                 datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(result[0]['name'], first[0]['name'])
        self.assertEqual(self.registry['next_number'], 2)

    def test_unconfirmed_nodes_do_not_consume_numbers(self):
        collector.admit(self.registry, {self.key: self.proxy}, {self.key: dict(ok=False)}, self.now)
        self.assertEqual(self.registry['next_number'], 1)
        changed = dict(self.proxy, uuid='new credential')
        other = collector.identity(changed)
        result = collector.admit(self.registry, {self.key: self.proxy, other: changed},
                                 {self.key: dict(ok=True), other: dict(ok=True)}, self.now)
        self.assertEqual([p['name'] for p in result], ['VLESS_#1_2026nov7', 'VLESS_#2_2026nov7'])

    def test_incomplete_sweep_cannot_be_published(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            collector.admit(self.registry, {self.key: self.proxy}, {}, self.now)

    def test_failed_source_retains_private_nodes_for_recheck(self):
        with patch.object(collector, 'fetch', side_effect=OSError), patch.object(collector.time, 'sleep'):
            _, nodes, status = collector.source_nodes(('https://example.com', [self.proxy]), Path('core'))
        self.assertEqual(nodes, [self.proxy])
        self.assertFalse(status['ok'])

    def test_discovery_deduplicates_and_keeps_igareck(self):
        body = b'[date][20][one][https://raw.githubusercontent.com/a/b/main/sub]\n' * 2
        urls = collector.discover(body + b'#[x][x][x][https://raw.githubusercontent.com/ignored/sub]\n')
        self.assertEqual(urls, [collector.IGARECK, 'https://raw.githubusercontent.com/a/b/main/sub'])

    def test_corrupt_registry_is_never_replaced_with_new_sequence(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'registry.json'
            self.assertEqual(collector.load_registry(path)['next_number'], 1)
            bad = copy.deepcopy(self.registry)
            bad['entries']['a'] = dict(number=1)
            collector.atomic_json(path, bad)
            with self.assertRaises(ValueError):
                collector.load_registry(path)

    def test_interrupted_publication_resumes_complete_pending_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Github list').mkdir()
            values = {'registry.json': self.registry, 'nova-list.json': {'proxies': []}, 'status.json': {'complete': True}}
            collector.atomic_json(root / 'pending.json', values)
            with patch.object(collector, 'publish', side_effect=RuntimeError):
                with self.assertRaises(RuntimeError):
                    collector.finish_pending(root, root)
            self.assertTrue((root / 'pending.json').exists())
            with patch.object(collector, 'publish'):
                collector.finish_pending(root, root)
            self.assertFalse((root / 'pending.json').exists())
            self.assertEqual(json.loads((root / 'Github list/registry.json').read_text()), self.registry)


if __name__ == '__main__':
    unittest.main()
