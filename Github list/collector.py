"""Nova list: verify public subscription nodes on Debian without OS routing changes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

AGGREGATOR = 'https://sub-aggregator.vercel.app/data.txt'
IGARECK = 'https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt'
MAX_BYTES = 8 * 1024 * 1024
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def fetch(url):
    # Ignore host proxy environment: this service must measure the Debian ISP path.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={'User-Agent': 'v2rayNG/1.10.6'})
    with opener.open(request, timeout=40) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('source exceeds size limit')
    return body


def discover(body):
    urls = [IGARECK]
    for line in body.decode('utf-8-sig').splitlines():
        if line.lstrip().startswith('#'):
            continue
        fields = re.findall(r'\[([^\]]*)\]', line)
        if len(fields) < 4:
            continue
        url = fields[3].strip()
        parts = urlsplit(url)
        # Only the public GitHub lists requested by the owner, never arbitrary fetch endpoints.
        if parts.scheme == 'https' and parts.hostname in ('raw.githubusercontent.com', 'github.com', 'raw.githack.com'):
            if parts.hostname == 'github.com' and '/blob/' in parts.path:
                url = 'https://raw.githubusercontent.com' + parts.path.replace('/blob/', '/', 1)
            if url not in urls:
                urls.append(url)
    return urls


def identity(proxy):
    value = dict(proxy)
    value.pop('name', None)
    if str(value.get('dialer-proxy', '')).upper() == 'DIRECT':
        value.pop('dialer-proxy')
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def admit(registry, candidates, results, now):
    """Only first successful HTTPS admission allocates a permanent global number/date."""
    entries = registry['entries']
    for entry in entries.values():
        entry['active'] = False
    active = []
    for key, proxy in candidates.items():
        result = results.get(key)
        if result is None:
            raise ValueError('incomplete verification; previous publication retained')
        if not result['ok']:
            continue
        protocol = re.sub('[^A-Z0-9]', '', str(proxy['type']).upper())
        entry = entries.get(key)
        if entry is None:
            date = f'{now.year}{MONTHS[now.month - 1]}{now.day}'
            entry = dict(number=registry['next_number'], added=date, protocol=protocol, active=True)
            entries[key] = entry
            registry['next_number'] += 1
        entry['active'] = True
        name = f'{entry["protocol"]}_#{entry["number"]}_{entry["added"]}'
        active.append((entry['number'], dict(proxy, name=name)))
    return [proxy for _, proxy in sorted(active)]


def load_registry(path):
    if not path.exists():
        return {'version': 1, 'next_number': 1, 'entries': {}}
    registry = json.loads(path.read_text(encoding='utf-8'))
    if registry.get('version') != 1 or not isinstance(registry.get('entries'), dict):
        raise ValueError('invalid identity registry; refusing to renumber profiles')
    numbers = [entry['number'] for entry in registry['entries'].values()]
    if len(numbers) != len(set(numbers)) or registry['next_number'] <= max(numbers, default=0):
        raise ValueError('invalid sequence; refusing to renumber profiles')
    return registry


def native_import(binary, body):
    process = subprocess.run([str(binary), 'import'], input=body, capture_output=True, timeout=120,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode:
        raise ValueError('core rejected source')
    return json.loads(process.stdout)


def source_nodes(item, binary):
    url, previous = item
    for attempt in range(2):
        try:
            parsed = native_import(binary, fetch(url))
            nodes = parsed.get('proxies', [])
            # A nonempty body that cannot be parsed is a source failure, not an empty update.
            if not nodes:
                raise ValueError('no supported nodes')
            return url, nodes, dict(ok=True, parsed=len(nodes), skipped=parsed.get('skipped', 0))
        except (OSError, ValueError, subprocess.SubprocessError):
            if attempt == 0:
                time.sleep(1)
    return url, previous, dict(ok=False, retained=len(previous))


def verify(binary, candidates, workers, seconds, work):
    results = {}
    pairs = list(candidates.items())
    for start in range(0, len(pairs), 1000):
        batch = pairs[start:start + 1000]
        request = json.dumps({'proxies': [p for _, p in batch]}).encode()
        if len(request) > MAX_BYTES:
            raise ValueError('probe batch too large')
        # Private files carry upstream credentials. Never copy these into logs or public artifacts.
        request_path = work / 'probe-request.json'
        request_path.write_bytes(request)
        seen = set()
        with request_path.open('rb') as input_stream:
            with subprocess.Popen([str(binary), 'probe-list', '--workers', str(workers), '--timeout', str(seconds)],
                                  stdin=input_stream, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
                for line in process.stdout:
                    result = json.loads(line)
                    index = result['index']
                    if index in seen or not 0 <= index < len(batch):
                        raise ValueError('invalid probe result')
                    seen.add(index)
                    results[batch[index][0]] = result
                code = process.wait()
        if code or len(seen) != len(batch):
            raise RuntimeError('probe process incomplete; previous publication retained')
        print(f'checked={len(results)}/{len(pairs)} confirmed={sum(r["ok"] for r in results.values())}', flush=True)
    return results


def git(repo, *args):
    process = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True,
                             timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode:
        raise RuntimeError(f'git {args[0]} failed; publication pending')
    return process.stdout


def publish(repo):
    paths = ['Github list/nova-list.json', 'Github list/registry.json', 'Github list/status.json']
    git(repo, 'add', '--', *paths)
    if not git(repo, 'diff', '--cached', '--name-only', '--', *paths).strip():
        return
    git(repo, 'commit', '-m', 'Refresh verified Nova list', '--', *paths)
    for attempt in range(3):
        try:
            git(repo, 'pull', '--rebase')
            git(repo, 'push', 'origin', 'HEAD:main')
            return
        except RuntimeError:
            if attempt == 2:
                raise
            time.sleep(5)


def finish_pending(repo, work):
    pending = work / 'pending.json'
    if not pending.exists():
        return
    values = json.loads(pending.read_text(encoding='utf-8'))
    if set(values) != {'registry.json', 'nova-list.json', 'status.json'}:
        raise ValueError('invalid pending publication')
    folder = repo / 'Github list'
    for name, value in values.items():
        atomic_json(folder / name, value)
    publish(repo)
    pending.unlink()


def run(args):
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    folder = args.repo.resolve() / 'Github list'
    if args.publish:
        finish_pending(args.repo.resolve(), work)
        # Also retries a previous completed commit whose upload failed.
        git(args.repo, 'pull', '--rebase')
        git(args.repo, 'push', 'origin', 'HEAD:main')
    cache_path = work / 'sources.json'
    cached = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    try:
        urls = discover(fetch(AGGREGATOR))
        if len(urls) < 2:
            raise ValueError('aggregator supplied no GitHub sources')
        atomic_json(work / 'source-urls.json', urls)
    except (OSError, ValueError):
        if not (work / 'source-urls.json').exists():
            raise RuntimeError('source discovery failed; publication retained')
        urls = json.loads((work / 'source-urls.json').read_text())
    candidates, source_status, next_cache = {}, [], {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, (url, nodes, status) in enumerate(pool.map(
                lambda item: source_nodes(item, args.core), [(url, cached.get(url, [])) for url in urls])):
            next_cache[url] = nodes
            source_status.append(dict(index=index, **status))
            for proxy in nodes:
                candidates.setdefault(identity(proxy), proxy)
    if not candidates or not any(s['ok'] for s in source_status):
        raise RuntimeError('all sources unavailable; publication retained')
    atomic_json(cache_path, next_cache)
    print(f'sources={len(urls)} candidates={len(candidates)}', flush=True)
    results = verify(args.core, candidates, args.workers, args.timeout, work)
    retry = {key: candidates[key] for key, result in results.items() if not result['ok']}
    if retry:
        print(f'retry={len(retry)}', flush=True)
        results.update(verify(args.core, retry, max(1, args.workers // 2), args.timeout, work))
    now = datetime.now(timezone(timedelta(hours=3)))
    registry = load_registry(folder / 'registry.json')
    active = admit(registry, candidates, results, now)
    checked_at = now.isoformat(timespec='seconds')
    status = dict(version=1, checked_at=checked_at, complete=True, sources=source_status,
                  candidates=len(candidates), checked=len(results), working=len(active),
                  retired=len(registry['entries']) - len(active), interval_hours=12)
    values = {'registry.json': registry, 'nova-list.json': dict(nova_list=dict(version=1, checked_at=checked_at,
                count=len(active), complete=True), proxies=active), 'status.json': status}
    if args.publish:
        atomic_json(work / 'pending.json', values)
        finish_pending(args.repo.resolve(), work)
    else:
        for name, value in values.items():
            atomic_json(folder / name, value)
    print(f'complete checked={len(results)} working={len(active)}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--core', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=32, choices=range(1, 65))
    parser.add_argument('--timeout', type=int, default=9, choices=range(1, 61))
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    # Service also uses umask; direct/manual invocation must protect cached source credentials.
    os.umask(0o077)
    try:
        run(args)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        detail = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(f'Nova list failed: {detail}; previous publication retained', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
