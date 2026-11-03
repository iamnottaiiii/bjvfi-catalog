#!/usr/bin/env python3
"""Rebuild the SiteDesk lead catalog by checking all bjvfi sub-repos and
adding missing slugs.

The catalog lives in this repo (bjvfi-catalog) split into two files,
sites-1.json and sites-2.json, each a {repo: [slugs]} dict in the same
format the old single sites.json used. GitHub rejects files over 100 MB;
the combined catalog passed that, so it is kept in two parts and every
consumer reads both and merges them.

Fast path: a shallow blob-less git clone plus `git ls-tree HEAD` lists every
top-level directory in one shot. Merges (never deletes), so existing entries
are preserved and only slugs found in the repos but missing get added.
"""
import json
import os
import shutil
import subprocess
import sys

OWNER = "iamnottaiiii"
# bjvfi1-8 plus bjvfi10-20 (lead batches, added 2026-11-03). bjvfi9 was deleted 2026-09-25 (its sites moved to bjvfi7)
SUB_REPOS = [f"bjvfi{i}" for i in range(1, 9)] + [f"bjvfi{i}" for i in range(10, 21)]
TOKEN=<redacted>
PART_PATHS = ["sites-1.json", "sites-2.json"]
WORKDIR_BASE = os.environ.get("REBUILD_WORKDIR", "/tmp/sitesjson-rebuild")


def get_top_level_dirs(repo):
    """Return the set of top-level directory names (site slugs) in a repo."""
    workdir = os.path.join(WORKDIR_BASE, repo)
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(WORKDIR_BASE, exist_ok=True)
    if TOKEN:
        url = f"https://x-access-token:{TOKEN}@github.com/{OWNER}/{repo}.git"
    else:
        url = f"https://github.com/{OWNER}/{repo}.git"
    clone = subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none",
         "--no-checkout", url, workdir],
        capture_output=True, text=True, timeout=1200)
    if clone.returncode != 0:
        raise RuntimeError(
            f"git clone failed for {repo}: {clone.stderr[-500:]}")
    try:
        ls = subprocess.run(
            ["git", "-C", workdir, "ls-tree", "HEAD"],
            capture_output=True, text=True, timeout=600, check=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    dirs = set()
    for line in ls.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, name = line.split("\t", 1)
        parts = meta.split()
        if (len(parts) >= 2 and parts[1] == "tree"
                and name and not name.startswith(".")):
            dirs.add(name)
    return dirs


def split_catalog(catalog):
    """Split the merged {repo: [slugs]} catalog into two parts by repo
    order, first part taking repos until it reaches half the slugs."""
    total = sum(len(catalog.get(r, [])) for r in SUB_REPOS)
    half = total // 2
    part1, part2, acc = {}, {}, 0
    for repo in SUB_REPOS:
        slugs = catalog.get(repo, [])
        if acc < half:
            part1[repo] = slugs
            acc += len(slugs)
        else:
            part2[repo] = slugs
    return part1, part2


def main():
    catalog = {}
    for path in PART_PATHS:
        if os.path.exists(path):
            with open(path) as f:
                for repo, slugs in json.load(f).items():
                    catalog.setdefault(repo, slugs)

    total_added = 0
    for repo in SUB_REPOS:
        print(f"Checking {repo}...", flush=True)
        try:
            live_dirs = get_top_level_dirs(repo)
        except Exception as e:
            print(f"  ERROR reading {repo}: {e} (keeping existing entries)",
                  file=sys.stderr)
            continue
        existing = set(catalog.get(repo, []))
        missing = live_dirs - existing
        if missing:
            catalog[repo] = sorted(existing | live_dirs)
            total_added += len(missing)
            print(f"  added {len(missing):,} missing slugs "
                  f"({len(live_dirs):,} in repo, {len(existing):,} listed)",
                  flush=True)
        else:
            print(f"  OK: {len(existing):,} slugs, nothing missing",
                  flush=True)

    part1, part2 = split_catalog(catalog)
    for path, part in zip(PART_PATHS, (part1, part2)):
        with open(path, "w") as f:
            json.dump(part, f, separators=(",", ":"))

    grand_total = sum(len(v) for v in catalog.values())
    print(f"\nDone. Added {total_added:,} missing slugs. "
          f"Catalog total: {grand_total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
