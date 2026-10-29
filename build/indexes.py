#!/usr/bin/env python3
"""Build all four citation indexes (data/talmud, data/targum, data/midrash, data/sources) in one run.

Each index reads the plain text of every entry; run together, that text is built once and shared, and the
indexes are built two at a time.
usage: python3 build/indexes.py SITE_DIR"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import talmud_index as T

_texts = list(T.entry_texts())
T.entry_texts = lambda: iter(_texts)

import targum_index, midrash_index, sources_index

# two processes (the machine has two cores): the Talmud index in one, the other three in the other
if os.fork() == 0:
    T.main(); sys.stdout.flush(); os._exit(0)
for mod in (targum_index, midrash_index, sources_index):
    mod.main()
_, status = os.wait()
sys.exit(1 if status else 0)
