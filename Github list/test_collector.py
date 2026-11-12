import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import collector

# The tests were written around batches of fifty; production uses a larger batch.
collector.PUBLISH_BATCH_SIZE = 50


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
        changed = dict(self.proxy, server='other.example.com', uuid='new credential')
        other = collector.identity(changed)
        result = collector.admit(self.registry, {self.key: self.proxy, other: changed},
                                 {self.key: dict(ok=True), other: dict(ok=True)}, self.now)
        self.assertEqual([p['name'] for p in result], ['VLESS_#2_2026nov7', 'VLESS_#1_2026nov7'])

    def test_one_endpoint_is_published_once(self):
        # Same server:port:SNI with another account or cosmetic options = a duplicate.
        twin = dict(self.proxy, uuid='another account', udp=True)
        cdn = dict(self.proxy, server='162.159.1.1', **{'ws-opts': {'headers': {'Host': 'a.example'}}})
        cdn_other = dict(cdn, **{'ws-opts': {'headers': {'Host': 'b.example'}}})
        candidates = {collector.identity(p): p for p in (self.proxy, twin, cdn, cdn_other)}
        results = {key: dict(ok=True, ms=100 + i) for i, key in enumerate(candidates)}
        result = collector.admit(self.registry, candidates, results, self.now)
        self.assertEqual(len(result), 3)
        endpoints = [collector.endpoint_key(p) for p in result]
        self.assertEqual(len(endpoints), len(set(endpoints)))
        # A node that already had a number keeps it over a faster newcomer on the same endpoint.
        results[collector.identity(twin)] = dict(ok=True, ms=1)
        again = collector.admit(self.registry, candidates, results, self.now)
        self.assertEqual({p['name'] for p in again}, {p['name'] for p in result})

    def test_list_carries_checker_latency(self):
        result = collector.admit(self.registry, {self.key: self.proxy}, {self.key: dict(ok=True, ms=321)}, self.now)
        self.assertEqual(collector.latencies(self.registry, result), [321])

    def test_list_head_is_the_most_recently_verified(self):
        nodes = [dict(self.proxy, server=f'n{i}.example.com') for i in range(3)]
        keys = [collector.identity(n) for n in nodes]
        results = {keys[0]: dict(ok=True, ms=10, at=300), keys[1]: dict(ok=True, ms=500, at=900),
                   keys[2]: dict(ok=True, ms=20, at=300)}
        listed = collector.admit(self.registry, dict(zip(keys, nodes)), results, self.now)
        self.assertEqual([p['server'] for p in listed], ['n1.example.com', 'n0.example.com', 'n2.example.com'])
        # A failing verdict never touches the stamp, a later pass moves the profile up.
        results[keys[0]] = dict(ok=True, ms=10, at=1200)
        results[keys[1]] = dict(ok=False)
        again = collector.admit(self.registry, dict(zip(keys, nodes)), results, self.now)
        self.assertEqual([p['server'] for p in again], ['n0.example.com', 'n2.example.com'])

    def test_pages_hold_fifty_and_parse_like_the_whole_list(self):
        proxies = [dict(self.proxy, name=f'p{i}') for i in range(120)]
        files = collector.pages_of(proxies, list(range(120)), '2026-11-12T00:00:00+03:00')
        index = files['pages/index.json']['nova_list_pages']
        self.assertEqual((index['pages'], index['count'], index['page_size']), (3, 120, 50))
        self.assertEqual(files['pages/index.json']['files'], ['page-001.json', 'page-002.json', 'page-003.json'])
        last = files['pages/page-003.json']
        self.assertEqual((last['nova_list']['count'], len(last['proxies']), len(last['ms'])), (20, 20, 20))
        self.assertEqual(files['pages/page-001.json']['proxies'][0]['name'], 'p0')
        self.assertEqual(collector.pages_of([], [], 'x')['pages/index.json']['nova_list_pages']['pages'], 0)

    def test_credential_key_ignores_remarks_and_cosmetics(self):
        a = dict(self.proxy, name='x', udp=True)
        b = dict(self.proxy, name='y')
        self.assertEqual(collector.credential_key(a), collector.credential_key(b))

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

    def test_known_due_profiles_are_checked_before_new_and_recent(self):
        def proxy(n):
            return dict(self.proxy, server=f'h{n}.example.com')
        keys = {n: collector.identity(proxy(n)) for n in range(5)}
        now = datetime(2026, 11, 9, tzinfo=timezone.utc)
        hour = 3600
        entries = {
            keys[0]: dict(number=1, added='x', protocol='VLESS', active=True, checked_ts=int(now.timestamp()) - 2 * hour),   # recent
            keys[1]: dict(number=2, added='x', protocol='VLESS', active=False, checked_ts=int(now.timestamp()) - 20 * hour),  # due, newer
            keys[2]: dict(number=3, added='x', protocol='VLESS', active=False),                                              # due, never stamped
        }
        registry = dict(version=1, next_number=4, entries=entries)
        candidates = {keys[n]: proxy(n) for n in (4, 0, 3, 1, 2)}  # 3 and 4 are new
        order = list(collector.prioritize(candidates, registry, now))
        self.assertEqual(order, [keys[2], keys[1], keys[4], keys[3], keys[0]])

    def test_progressive_publication_preserves_old_nodes_until_full_sweep(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            folder = repo / 'Github list'
            folder.mkdir()
            old = collector.admit(self.registry, {self.key: self.proxy}, {self.key: dict(ok=True)}, self.now)
            collector.atomic_json(folder / 'registry.json', self.registry)
            collector.atomic_json(folder / 'nova-list.json', {'proxies': old})
            fresh = [dict(self.proxy, server=f'new-{i}.example.com') for i in range(103)]
            fresh_keys = [collector.identity(proxy) for proxy in fresh]
            def verify(binary, candidates, workers, seconds, work, checkpoint, bulk=0, google=False):
                if checkpoint is None:  # confirmation pass
                    return {key: dict(ok=True) for key in candidates}
                results = {}
                for i, key in enumerate(fresh_keys, 1):
                    results[key] = dict(ok=True)
                    checkpoint(results)
                    intermediate = json.loads((folder / 'nova-list.json').read_text())
                    self.assertEqual(len(intermediate['proxies']), 1 + (i // 50) * 50)
                    if i >= 50:
                        self.assertFalse(json.loads((folder / 'status.json').read_text())['complete'])
                return results
            args = SimpleNamespace(repo=repo, work=repo / 'cache', core=repo / 'core', bulk=0, any_target=False,
                                   workers=1, timeout=1, publish=False)
            with patch.object(collector, 'fetch', return_value=b'[date][1][source][https://raw.githubusercontent.com/a/b/main/sub]'), \
                    patch.object(collector, 'source_nodes', side_effect=lambda item, core: (item[0], fresh, dict(ok=True))), \
                    patch.object(collector, 'verify', side_effect=verify):
                collector.run(args)
            final = json.loads((folder / 'nova-list.json').read_text())
            self.assertEqual(len(final['proxies']), 103)
            self.assertIn('_#104_', final['proxies'][0]['name'])
            history = collector.load_registry(folder / 'registry.json')
            self.assertFalse(history['entries'][self.key]['active'])
            self.assertTrue(json.loads((folder / 'status.json').read_text())['complete'])

    def test_retry_pass_also_publishes_fifty_ready_nodes_before_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            folder = repo / 'Github list'
            folder.mkdir()
            nodes = [dict(self.proxy, server=f'retry-{i}.example.com') for i in range(50)]
            keys = [collector.identity(node) for node in nodes]
            passes = []
            def verify(binary, candidates, workers, seconds, work, checkpoint, bulk=0, google=False):
                passes.append(len(candidates))
                if checkpoint is None:  # confirmation pass drops one flapping node
                    return {key: dict(ok=key != keys[0]) for key in candidates}
                results = {}
                for i, key in enumerate(candidates):
                    results[key] = dict(ok=len(passes) == 2 or i < 20)
                    if results[key]['ok']:
                        checkpoint(results)
                if len(passes) == 1:
                    self.assertFalse((folder / 'nova-list.json').exists())
                else:
                    self.assertEqual(len(json.loads((folder / 'nova-list.json').read_text())['proxies']), 50)
                    self.assertFalse(json.loads((folder / 'status.json').read_text())['complete'])
                return results
            args = SimpleNamespace(repo=repo, work=repo / 'cache', core=repo / 'core', bulk=0, any_target=False,
                                   workers=2, timeout=1, publish=False)
            with patch.object(collector, 'fetch', return_value=b'[x][x][x][https://raw.githubusercontent.com/a/b/main/sub]'), \
                    patch.object(collector, 'source_nodes', side_effect=lambda item, core: (item[0], nodes, dict(ok=True))), \
                    patch.object(collector, 'verify', side_effect=verify):
                collector.run(args)
            self.assertEqual(passes, [50, 30, 50])
            self.assertEqual(len(json.loads((folder / 'nova-list.json').read_text())['proxies']), 49)


if __name__ == '__main__':
    unittest.main()
