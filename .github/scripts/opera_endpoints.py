#!/usr/bin/env python3
"""Publish the list of usable Opera (SurfEasy) proxy endpoints.

Why this exists. SurfEasy's `discover` call answers with endpoints picked for
the caller's location, and from Russia the answer is a set nothing can reach.
Nova therefore needs the answer as seen from somewhere else. Builds that carry
the API relay password can ask through the relay; the F-Droid build cannot --
a password inside published, reproducible sources stops being a password the
day it ships. So the list is published instead: this script runs on a GitHub
runner, asks `discover` from there and writes the addresses next to
`apk_version.json`, where every build already looks for update data.

Only `ip:port` is published. `opera-proxy -list-proxies` also prints the proxy
login and password of the anonymous device it just registered -- those are
per-device, useless to anyone else, and are never written out or echoed into
the workflow log. Nova registers its own device and only reuses the address
(`-override-proxy-address`).
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# Region codes as opera-proxy spells them. Nova asks for exactly these two:
# "EU" and "AM" (the user-facing label for AM is "US").
REGIONS = ("EU", "AM")

# Two passes per region. Each run registers a fresh anonymous device and the
# answer differs between registrations, so a second pass widens the set for
# free. More than two stopped adding new addresses in practice.
PASSES = 2

# Nova keeps 16 addresses per region and tries the first two that are not
# cooling down. Publishing more than this is weight without effect.
MAX_PER_REGION = 8

RUN_TIMEOUT_SEC = 90


def parse_table(stdout: str) -> list[str]:
    """Pull `ip:port` out of what `-list-proxies` printed.

    The CSV table starts after a blank line; everything before it is the
    credentials block, which must not leak anywhere.
    """
    _, _, table = stdout.partition("\n\n")
    endpoints: list[str] = []
    for row in csv.reader(io.StringIO(table)):
        if len(row) < 3 or row[0].strip() == "host":
            continue
        address = row[1].strip()
        port = row[2].strip()
        if not address or not port.isdigit():
            continue
        endpoint = f"{address}:{port}"
        if endpoint not in endpoints:
            endpoints.append(endpoint)
    return endpoints


def discover(binary: str, region: str) -> list[str]:
    """Run one discover pass and return the addresses it listed."""
    proc = subprocess.run(
        [
            binary,
            "-country",
            region,
            "-list-proxies",
            "-timeout",
            "15s",
        ],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SEC,
    )
    if proc.returncode != 0:
        # stderr carries opera-proxy's own diagnostics and no credentials.
        print(f"  {region}: exit {proc.returncode}: {proc.stderr.strip()[:400]}", file=sys.stderr)
        return []

    return parse_table(proc.stdout)


def collect(binary: str) -> dict[str, list[str]]:
    regions: dict[str, list[str]] = {}
    for region in REGIONS:
        found: list[str] = []
        for attempt in range(PASSES):
            for endpoint in discover(binary, region):
                if endpoint not in found:
                    found.append(endpoint)
            print(f"  {region}: pass {attempt + 1}/{PASSES}, {len(found)} address(es) so far")
        if found:
            regions[region] = found[:MAX_PER_REGION]
    return regions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, help="path to the opera-proxy executable")
    parser.add_argument("--output", required=True, help="path of the JSON file to write")
    args = parser.parse_args()

    regions = collect(args.binary)
    if not regions:
        # Loud failure on purpose: a red run is information, an empty list
        # published over a good one is a silent outage for every client.
        print("discover returned nothing for any region", file=sys.stderr)
        return 1

    previous = {}
    if os.path.exists(args.output):
        try:
            with open(args.output, encoding="utf-8") as handle:
                previous = json.load(handle)
        except (OSError, ValueError):
            previous = {}

    if previous.get("regions") == regions:
        # Rewriting only the timestamp would produce a commit an hour, forever.
        print("Endpoint list unchanged.")
        return 0

    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "surfeasy-discover",
        "regions": regions,
    }
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("Wrote " + ", ".join(f"{region}: {len(items)}" for region, items in regions.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
