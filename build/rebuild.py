#!/usr/bin/env python3
"""Rebuild the site's data/: make_site2.py, then indexes.py (about 40 seconds).

usage: python3 build/rebuild.py
The source files are found through build/paths.py. The indexes' full output goes to REPORTS/indexes.out;
only the last line of the build and the indexes' dropped and agreement counts are printed."""
import os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

os.chdir(paths.REPO)
for p in (paths.OUT2, paths.CURRENT, paths.BREAKS):
    if not os.path.exists(p): sys.exit("missing: %s (see build/paths.py)" % p)
r = subprocess.run([sys.executable, "-I", "build/make_site2.py", paths.OUT2, paths.REPO, paths.CURRENT],
                   env=dict(os.environ, BREAKS=paths.BREAKS), capture_output=True, text=True)
if r.returncode: sys.stderr.write(r.stdout + r.stderr); sys.exit(1)
print((r.stdout.strip().splitlines() or [""])[-1])
r = subprocess.run([sys.executable, "build/indexes.py", "."], capture_output=True, text=True)
open(paths.report("indexes.out"), "w").write(r.stdout + r.stderr)
if r.returncode: sys.stderr.write(r.stdout + r.stderr); sys.exit(1)
for line in r.stdout.splitlines():
    if re.search(r"dropped|agreement with Sefaria's links \(Bavli\)", line): print(line)
