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
# Every checkpoint is a commit of the whole list to the public repo; with thousands of
# working nodes a batch of 50 meant ~100 commits of a multi-megabyte file per sweep.
PUBLISH_BATCH_SIZE = 500

# Owner-supplied subscriptions (2026-11-08), fetched on every sweep in addition to the
# discovered GitHub lists. A tuple is one source with mirrors: the first mirror that
# answers wins, and the source is cached under its first URL. Dead at the time of adding
# (404 / unparseable) were left out: kort0881 clean+ru-sni, gitverse gidro, vpnsvpns mifa,
# OceaniaVPN okeania_auto, vpn.yzewe.ru, tunpass.online (personal key in the URL).
EXTRA_SOURCES = (
    'https://klwp-reproxy.vercel.app/vpn',
    'https://klwp-reproxy.vercel.app/bypass',
    'https://gitflic.ru/project/sigil/my-new-cool-project/blob/raw?file=whitelist',
    'https://raw.githubusercontent.com/ImSketch1337/vless-/refs/heads/main/BLWLservers.txt',
    'https://raw.githubusercontent.com/OVI-vpn/bs/main/premium.txt',
    'https://raw.githubusercontent.com/OVI-vpn/bs/main/full.txt',
    'https://bobrrvpn.neocities.org/blacklist.txt',
    'https://notorvpn.notorgamess.workers.dev/sub/notorvpn_plain',
    'https://raw.githubusercontent.com/gazeta404/rain_vpn_sub/main/subscribe.txt',
    'https://raw.githubusercontent.com/LSO-LinSpisokObhod/LSO-LinSpisokObhod.github.io/refs/heads/main/sub/ALL.txt',
    'https://raw.githubusercontent.com/solovyov-jenya2004/all_subs/refs/heads/main/final_sorted',
    'https://raw.githubusercontent.com/aviamastersgh/vpn-free-russia/main/all_configs.txt',
    'https://raw.githubusercontent.com/btsk161/Freeinternet_byMygalaru.github.io/refs/heads/main/premium.txt',
    'https://github.com/theakres/VPN/raw/main/all',
    'https://raw.githubusercontent.com/WSJuJuBA01/WS_Parser/refs/heads/main/subscription.txt',
    'https://github.com/vessel-web/CoolSubs/raw/refs/heads/main/Cool-White.txt',
    'https://raw.githubusercontent.com/vessel-web/CoolSubs/main/Cool-Black.txt',
    'https://raw.githubusercontent.com/3inker/v2ray-subscription/main/subs/all_ru.txt',
    'https://my-vpn.click/sub.txt',
    'https://raw.githubusercontent.com/coloramamoe/vless-parser/main/githubmirror/full.txt',
    'https://raw.githubusercontent.com/wlunlocker/vpn-configs/main/blacklist_all.txt',
    'https://raw.githubusercontent.com/gooseteam-hackers/freevpn-cracks/refs/heads/main/subscription_default.txt',
    'https://sub.vlessfo.ru/vlessforu/working_configs.txt',
    'https://raw.githubusercontent.com/Buffetbarko/Universal-Proxy-Config-Parser-/main/blacklist_vpn.txt',
    'https://raw.githubusercontent.com/Buffetbarko/Universal-Proxy-Config-Parser-/main/whitelist_vpn.txt',
    'https://gist.github.com/PizdukMod/0270547cabecdd08527e2645f3b3672c/raw/8ad47b69ec9343eeb7190695cc05c86b3cca6198/sub',
    'https://gist.github.com/PizdukMod/66d338db037b345022b7d827ca0112f1/raw/984e3731b25ba5bc3286c0bfe0e44c967c43d46a/wl',
    'https://gist.github.com/PizdukMod/7456b4e460bb7a358b8916368ee92c50/raw/6b78913ef3d45efa3a7db43e6366a195054249a7/Mixer',
    'https://github.com/aneek0/goida-vpn-configs/raw/refs/heads/main/githubmirror/1.txt',
    'https://github.com/aneek0/goida-vpn-configs/raw/refs/heads/main/githubmirror/6.txt',
    'https://github.com/aneek0/goida-vpn-configs/raw/refs/heads/main/githubmirror/22.txt',
    'https://github.com/aneek0/goida-vpn-configs/raw/refs/heads/main/githubmirror/23.txt',
    'https://github.com/aneek0/goida-vpn-configs/raw/refs/heads/main/githubmirror/24.txt',
    'https://github.com/aneek0/goida-vpn-configs/raw/refs/heads/main/githubmirror/25.txt',
    'https://github.com/aneek0/goida-vpn-configs/raw/refs/heads/main/githubmirror/26.txt',
    'https://raw.githubusercontent.com/andmailg/singbox-sub/main/vless_tcp.txt',
    'https://raw.githubusercontent.com/whoahaow/rjsxrd/refs/heads/main/githubmirror/bypass/bypass-all.txt',
    'https://gidroksi.fun/black-list',
    'https://raw.githubusercontent.com/flaafix/AetrisVPN-black-list/refs/heads/main/configs.txt',
    'https://raw.githubusercontent.com/flaafix/AetrisVPN/refs/heads/main/AetrisVPN.txt',
    # rtwo2/FastNodes per-protocol lists (owner-supplied 2026-11-09)
    'https://raw.githubusercontent.com/rtwo2/FastNodes/main/sub/protocols/vless.txt',
    'https://raw.githubusercontent.com/rtwo2/FastNodes/main/sub/protocols/vmess.txt',
    'https://raw.githubusercontent.com/rtwo2/FastNodes/main/sub/protocols/trojan.txt',
    'https://raw.githubusercontent.com/rtwo2/FastNodes/main/sub/protocols/ss.txt',
    'https://raw.githubusercontent.com/rtwo2/FastNodes/main/sub/protocols/hysteria2.txt',
    ('https://etoneya.su/1', 'https://etoneya.best/1', 'https://alley.serv00.net/1',
     'https://etoneya.baby', 'https://etoskam.ru/1', 'https://internet-tenshi.kangel.tech/1'),
    ('https://etoneya.su/youtube', 'https://etoneya.best/youtube', 'https://alley.serv00.net/youtube',
     'https://yt.etoneya.baby', 'https://etoskam.ru/youtube', 'https://internet-tenshi.kangel.tech/youtube'),
)
MIRRORS = {group[0]: group for group in EXTRA_SOURCES if isinstance(group, tuple)}
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    # The public list is downloaded by every client: no indentation there.
    compact = path.name == 'nova-list.json' or path.parent.name == 'pages'
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        if compact:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
        else:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def fetch(url):
    # Ignore host proxy environment: this service must measure the Debian ISP path.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={'User-Agent': 'v2rayNG/1.10.6'})
    error = None
    for attempt in range(3):
        try:
            with opener.open(request, timeout=12) as response:
                body = response.read(MAX_BYTES + 1)
            break
        except OSError as caught:
            error = caught
    else:
        raise error
    if len(body) > MAX_BYTES:
        raise ValueError('source exceeds size limit')
    return body


def fetch_any(urls):
    error = None
    for url in urls:
        try:
            return fetch(url)
        except (OSError, ValueError) as caught:
            error = caught
    raise error


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


def with_extra_sources(urls):
    out = list(urls)
    for source in EXTRA_SOURCES:
        key = source[0] if isinstance(source, tuple) else source
        if key not in out:
            out.append(key)
    return out


def _text(value):
    return str(value or '').strip().lower().strip('[]')


def _opts(proxy, *names):
    for name in names:
        value = proxy.get(name)
        if isinstance(value, dict):
            return value
    return {}


def endpoint_key(proxy):
    """Where traffic really goes: address, port and the backend name a CDN routes by.

    Two entries with the same key are the same server for a user, whatever their
    credentials or cosmetic options; the published list carries each key once.
    CDN fronts (Cloudflare IPs on 443) differ only by SNI/Host, so those belong in it.
    """
    headers = _opts(proxy, 'ws-opts', 'http-opts', 'h2-opts', 'xhttp-opts', 'httpupgrade-opts')
    host = headers.get('host') or (headers.get('headers') or {}).get('Host') or ''
    if isinstance(host, list):
        host = host[0] if host else ''
    name = proxy.get('servername') or proxy.get('sni') or host
    return '|'.join((_text(proxy.get('server')), str(proxy.get('port', '')).strip(), _text(name)))


def credential_key(proxy):
    """Same endpoint and same secret: one inbound account, checked once."""
    secret = (proxy.get('uuid') or proxy.get('password') or proxy.get('private-key')
              or proxy.get('auth-str') or proxy.get('auth_str') or proxy.get('auth') or '')
    return '|'.join((_text(proxy.get('type')), endpoint_key(proxy), str(secret).strip()))


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
    winners = {}
    for key, proxy in candidates.items():
        result = results.get(key)
        if result is None:
            raise ValueError('incomplete verification; previous publication retained')
        if not result['ok']:
            continue
        # Never two entries for one endpoint: a known number wins (stable names for
        # clients), then the faster answer, then the first seen.
        known = entries.get(key)
        rank = (0 if known else 1, known['number'] if known else 0, result.get('ms') or 10 ** 9)
        endpoint = endpoint_key(proxy)
        if endpoint not in winners or rank < winners[endpoint][0]:
            winners[endpoint] = (rank, key, proxy, result)
    active = []
    for _, key, proxy, result in sorted(winners.values(), key=lambda item: item[0]):
        protocol = re.sub('[^A-Z0-9]', '', str(proxy['type']).upper())
        entry = entries.get(key)
        if entry is None:
            date = f'{now.year}{MONTHS[now.month - 1]}{now.day}'
            entry = dict(number=registry['next_number'], added=date, protocol=protocol, active=True)
            entries[key] = entry
            registry['next_number'] += 1
        entry['active'] = True
        # A passing verdict moves the profile to the head; retained ones keep their stamp.
        if result.get('at'):
            entry['verified_ts'] = max(int(entry.get('verified_ts', 0)), int(result['at']))
        if result.get('ms'):
            entry['ms'] = int(result['ms'])
        name = f'{entry["protocol"]}_#{entry["number"]}_{entry["added"]}'
        active.append((entry, dict(proxy, name=name)))
    return [proxy for _, proxy in sorted(active, key=lambda item: list_rank(item[0]))]


def list_rank(entry):
    """Published order: most recently verified first, then the faster node, then the newer number.

    Clients probe the head of the list in batches of fifty and read further batches only
    when the head is short of live nodes, so the head must hold what was confirmed last.
    """
    return (-int(entry.get('verified_ts', 0)), int(entry.get('ms') or 10 ** 9), -entry['number'])


RECHECK_SECONDS = 12 * 3600
PAGE_SIZE = 50


def pages_of(proxies, ms, checked_at, size=PAGE_SIZE):
    """The list cut into pages of `size`: `pages/index.json` plus `pages/page-NNN.json`.

    A page is a complete snapshot of its own (same shape as `nova-list.json`), so a client
    parses it with the code that reads the whole list. Page 1 is the newest verified.
    """
    count = len(proxies)
    total = max(1, -(-count // size)) if count else 0
    files = {}
    names = []
    for number in range(1, total + 1):
        chunk = slice((number - 1) * size, number * size)
        name = f'pages/page-{number:03d}.json'
        names.append(name.split('/', 1)[1])
        files[name] = dict(nova_list=dict(version=1, checked_at=checked_at, count=len(proxies[chunk]),
                                          complete=True, page=number, pages=total),
                           proxies=proxies[chunk], ms=ms[chunk])
    files['pages/index.json'] = dict(nova_list_pages=dict(version=1, checked_at=checked_at, count=count,
                                                          page_size=size, pages=total), files=names)
    return files


def prioritize(candidates, registry, now):
    """Queue 1: known (registry) profiles due for a recheck, oldest check first (a profile
    that reappears in a source is known, so it jumps ahead). Queue 2: new profiles.
    Queue 3: known profiles checked less than 12 h ago. Every candidate is still checked."""
    entries = registry['entries']
    stamp = now.timestamp()
    due, new, fresh = [], [], []
    for key, proxy in candidates.items():
        entry = entries.get(key)
        if entry is None:
            new.append((key, proxy))
            continue
        last = entry.get('checked_ts', 0)
        (due if stamp - last >= RECHECK_SECONDS else fresh).append((last, key, proxy))
    due.sort(key=lambda item: item[0])
    fresh.sort(key=lambda item: item[0])
    return dict([(k, p) for _, k, p in due] + new + [(k, p) for _, k, p in fresh])


def latencies(registry, active):
    """Checker-side HTTPS 204 time per published node (0 = unknown), aligned with proxies.

    Clients order a fresh list by it instead of probing thousands of nodes themselves.
    """
    by_number = {entry['number']: entry.get('ms', 0) for entry in registry['entries'].values()}
    out = []
    for proxy in active:
        match = re.search(r'_#(\d+)_', proxy['name'])
        out.append(by_number.get(int(match.group(1)), 0) if match else 0)
    return out


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
            parsed = native_import(binary, fetch_any(MIRRORS.get(url, (url,))))
            nodes = parsed.get('proxies', [])
            # A nonempty body that cannot be parsed is a source failure, not an empty update.
            if not nodes:
                raise ValueError('no supported nodes')
            return url, nodes, dict(ok=True, parsed=len(nodes), skipped=parsed.get('skipped', 0))
        except (OSError, ValueError, subprocess.SubprocessError):
            if attempt == 0:
                time.sleep(1)
    return url, previous, dict(ok=False, retained=len(previous))


def verify(binary, candidates, workers, seconds, work, checkpoint=None, bulk=0, google=False):
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
            with subprocess.Popen([str(binary), 'probe-list', '--workers', str(workers), '--timeout', str(seconds),
                                   '--bulk', str(bulk)] + (['--google'] if google else []),
                                  stdin=input_stream, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
                for line in process.stdout:
                    result = json.loads(line)
                    index = result['index']
                    if index in seen or not 0 <= index < len(batch):
                        raise ValueError('invalid probe result')
                    seen.add(index)
                    result['at'] = int(time.time())
                    results[batch[index][0]] = result
                    if checkpoint and result['ok']:
                        checkpoint(results)
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
    paths = ['Github list/nova-list.json', 'Github list/registry.json', 'Github list/status.json',
             'Github list/pages']
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
    base = {'registry.json', 'nova-list.json', 'status.json'}
    if not base <= set(values) or any(name not in base and not name.startswith('pages/') for name in values):
        raise ValueError('invalid pending publication')
    folder = repo / 'Github list'
    # Pages the list no longer fills are removed, so a shrunk list never keeps an old tail.
    pages = folder / 'pages'
    pages.mkdir(exist_ok=True)
    for old in pages.glob('page-*.json'):
        if f'pages/{old.name}' not in values:
            old.unlink()
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
        fallback = work / 'source-urls.json'
        if not fallback.exists():
            fallback = folder / 'sources.json'
        if not fallback.exists():
            raise RuntimeError('source discovery failed; publication retained')
        urls = json.loads(fallback.read_text())
        print('source discovery unavailable; using last known GitHub sources', flush=True)
    urls = with_extra_sources(urls)
    candidates, source_status, next_cache = {}, [], {}
    seen_credentials = set()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, (url, nodes, status) in enumerate(pool.map(
                lambda item: source_nodes(item, args.core), [(url, cached.get(url, [])) for url in urls])):
            next_cache[url] = nodes
            source_status.append(dict(index=index, **status))
            for proxy in nodes:
                credential = credential_key(proxy)
                if credential in seen_credentials:
                    continue
                seen_credentials.add(credential)
                candidates.setdefault(identity(proxy), proxy)
    if not candidates or not any(s['ok'] for s in source_status):
        raise RuntimeError('all sources unavailable; publication retained')
    atomic_json(cache_path, next_cache)
    print(f'sources={len(urls)} candidates={len(candidates)}', flush=True)
    registry = load_registry(folder / 'registry.json')
    candidates = prioritize(candidates, registry, datetime.now(timezone.utc))
    previous = folder / 'nova-list.json'
    retained = {identity(p): p for p in json.loads(previous.read_text())['proxies']} if previous.exists() else {}

    def snapshot(results, complete, additions=None):
        now = datetime.now(timezone(timedelta(hours=3)))
        chosen = candidates
        verdicts = results
        if not complete:
            chosen = dict(retained)
            chosen.update(additions or {})
            verdicts = {key: dict(ok=True, at=results[key]['at']) if key in results and results[key].get('at')
                        and results[key].get('ok') else dict(ok=True) for key in chosen}
        for key in results:
            if key in registry['entries']:
                registry['entries'][key]['checked_ts'] = int(now.timestamp())
        active = admit(registry, chosen, verdicts, now)
        checked_at = now.isoformat(timespec='seconds')
        status = dict(version=1, checked_at=checked_at, complete=complete, sources=source_status,
                      candidates=len(candidates), checked=len(results), working=len(active),
                      retired=len(registry['entries']) - len(active), interval_hours=12)
        values = {'registry.json': registry, 'nova-list.json': dict(nova_list=dict(version=1,
                    checked_at=checked_at, count=len(active), complete=True), proxies=active,
                    ms=latencies(registry, active)), 'status.json': status}
        values.update(pages_of(active, values['nova-list.json']['ms'], checked_at))
        if args.publish:
            atomic_json(work / 'pending.json', values)
            finish_pending(args.repo.resolve(), work)
        else:
            for name, value in values.items():
                atomic_json(folder / name, value)
        return len(active)

    cumulative = {}

    def checkpoint(results):
        cumulative.update(results)
        ready = {key: candidates[key] for key, result in cumulative.items()
                 if result['ok'] and key not in retained}
        # Flush fifty newly confirmed profiles at a time, also during the retry
        # pass. Previous active profiles remain until a complete sweep retires them.
        while len(ready) >= PUBLISH_BATCH_SIZE:
            additions = dict(list(ready.items())[:PUBLISH_BATCH_SIZE])
            try:
                count = snapshot(cumulative, False, additions)
            except RuntimeError as error:
                print(f'checkpoint upload pending: {error}', flush=True)
                return
            retained.update(additions)
            for key in additions:
                del ready[key]
            print(f'published batch added={len(additions)} checked={len(cumulative)} working={count}', flush=True)

    def recheck_published():
        """Published profiles first: dead ones leave the list now, confirmed ones move to its head.

        The hunt for new nodes takes hours; without this a node that died stays published for
        the whole sweep. All-failed is read as a checker outage, not as a dead list.
        """
        known = dict(retained)
        if not known:
            return
        goal = not args.any_target
        outcome = verify(args.core, known, args.workers, args.timeout, work, None, args.bulk, goal)
        again = {key: known[key] for key, r in outcome.items() if not r['ok']}
        if again:
            outcome.update(verify(args.core, again, max(1, args.workers // 2), args.timeout, work, None,
                                  args.bulk, goal))
        passed = {key: known[key] for key, r in outcome.items() if r['ok']}
        if passed:
            confirm = verify(args.core, passed, args.workers, args.timeout, work, None, args.bulk, goal)
            outcome.update(confirm)
            passed = {key: known[key] for key, r in confirm.items() if r['ok']}
        if not passed:
            print('published profiles all failed; checker outage assumed, list kept', flush=True)
            return
        retained.clear()
        retained.update(passed)
        count = snapshot(outcome, False)
        print(f'recheck published={len(known)} kept={count}', flush=True)

    try:
        recheck_published()
    except (RuntimeError, ValueError, OSError) as error:
        print(f'recheck of published profiles skipped: {error}', flush=True)

    results = verify(args.core, candidates, args.workers, args.timeout, work, checkpoint, args.bulk, not args.any_target)
    cumulative.update(results)
    retry = {key: candidates[key] for key, result in results.items() if not result['ok']}
    if retry:
        print(f'retry={len(retry)}', flush=True)
        results.update(verify(args.core, retry, max(1, args.workers // 2), args.timeout, work, checkpoint, args.bulk, not args.any_target))
    # Free nodes flap: one 204+bulk in a retry pass let in a third of a list that was
    # dead from the same network minutes after publishing. Keep only nodes that pass again.
    passed = {key: candidates[key] for key, result in results.items() if result['ok']}
    if passed:
        confirm = verify(args.core, passed, args.workers, args.timeout, work, None, args.bulk, not args.any_target)
        results.update(confirm)
        print(f'confirm={len(passed)} kept={sum(1 for r in confirm.values() if r["ok"])}', flush=True)
    count = snapshot(results, True)
    print(f'complete checked={len(results)} working={count}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--core', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=32, choices=range(1, 65))
    parser.add_argument('--timeout', type=int, default=9, choices=range(1, 61))
    # A 204 passes where Russian TSPU freezes TCP to foreign hosting after 12-40 KB; such a node
    # looks alive yet loads no page. Require this many bytes through the node (0 = 204 only).
    parser.add_argument('--bulk', type=int, default=40 * 1024)
    # Without it a node that reaches only Cloudflare/gstatic passes and loads no real site.
    parser.add_argument('--any-target', action='store_true', help='accept any 204 target, not only www.google.com')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.bulk <= 4 << 20:
        parser.error('--bulk must be 0..4 MiB')
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
