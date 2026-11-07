# Nova list

Built-in Nova subscription, refreshed every 12 hours:

`https://raw.githubusercontent.com/confeden/nova_updates/main/Github%20list/nova-list.json`

Sources: [igareck BLACK_VLESS_RUS](https://github.com/igareck/vpn-configs-for-russia)
and the public GitHub subscriptions discovered from
[sub-aggregator](https://sub-aggregator.vercel.app/data.txt) on every sweep.
Duplicate profiles are checked once. Unsupported/invalid configurations are counted
in `status.json`; they are never advertised as working.

Checks run on Debian on a Russian residential line. Each Mihomo protocol adapter
carries only its own HTTPS requests: no TUN, system proxy, DNS changes, firewall or
route changes. A profile is published only after a certificate-validated HTTPS
`204` from Google, gstatic or Cloudflare, without redirects or direct fallback.
Unreachable TCP endpoints have a 1.5 second dial budget; other checks have a total
9 second budget across three HTTPS targets. Failures get a second pass with reduced concurrency. Regional and ISP differences
remain possible; a successful check is evidence from this checker, not every ISP.

Names are `PROTOCOL_#NUMBER_YYYYmonD`, for example `VLESS_#24_2026nov7`.
The global sequence starts at 1. `registry.json` permanently retains fingerprint,
number and first successful admission date, including inactive profiles. Remarks
do not affect identity. A returning working profile keeps its original number/date.
Old private keys are not stored in the registry; only active public-source profiles
are published. Protocol/endpoint/authentication/transport changes define a new profile.

`status.json` records progress and whether the full sweep is complete. Working
profiles are added after each 1000 checked candidates, so the first list becomes
available while the initial full check continues. A failed download keeps that
source's private cache and rechecks it; a failed discovery uses the last known
source URLs. Partial checkpoints only add freshly verified profiles and retain
previously published ones. Only after a complete run are unconfirmed profiles removed while
their identity history remains. Fetching failures do not erase the entire list.

The Debian `nova-list.timer` runs at 00:00 and 12:00 UTC (03:00/15:00 Moscow).
Missed runs execute after boot. The service has no network administration privileges,
uses a dedicated account, and publishes with a repository-specific SSH deploy key.
Inspect: `systemctl status nova-list.timer nova-list.service` and
`journalctl -u nova-list.service`. A failed service is visible in systemd.

Rebuild the GPL-3.0 checker from the pinned source snapshot in `core/`:
Inside `core/`, run `CGO_ENABLED=0 go build -trimpath -o ../nova-proxy .`.
Python requires 3.9+ and only stdlib.
Install collector/core under `/opt/nova-list`, units under `/etc/systemd/system`,
and clone this repository under `/var/lib/nova-list/repo` for user `nova-list`.
Private cache/key files belong under `/var/lib/nova-list`, never this repository.
