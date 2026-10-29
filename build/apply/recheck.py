"""Mark every proofing card with whether what it points at is still on the site as built now."""
import json, re, html, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
S = paths.REPO
P = json.load(open(S + '/data/pages.json'))['pages']; ids = [p[0] for p in P]
cache = {}
def text(i):
    c = i // 10
    if c not in cache: cache[c] = json.load(open(S + '/data/c%03d.json' % c))
    a = cache[c][i % 10]; h = ''.join(a) if isinstance(a, list) else a
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', h)))
sq = lambda s: re.sub(r'\s+', ' ', s)
stats = {}
for g in sorted(glob.glob(os.path.join(paths.PROOFING, 'data', 'chunk_*.json'))):
    D = json.load(open(g))
    for it in D['items']:
        it.pop('still', None)
        s = it.get('site') or ''
        if it['type'] in ('column break differs', 'low-match') or not s: continue
        m = re.search('⟦([^⟧]*)⟧', s)
        if m:
            left, mid, right = s[:m.start()], m.group(1), s[m.end():]
            mid = '' if mid.strip() in ('', '‸') else mid
        else:
            left, mid, right = s, '', ''
        left = sq(left.replace('…', '')).strip()[-28:]; right = sq(right.replace('…', '')).strip()[:28]
        pg = str(it['page'])
        if pg not in ids: continue
        i = ids.index(pg); T = ' '.join(text(j) for j in range(max(0, i - 1), min(len(ids), i + 2)))
        T2 = T.replace(' ', '')
        needle = (left + mid + right).replace(' ', '') if mid else (left + right).replace(' ', '')
        # still there if the text around the difference reads as it did when the card was made
        it['still'] = needle in T2 if len(needle) > 12 else None
        stats[(it['type'], it['still'])] = stats.get((it['type'], it['still']), 0) + 1
    json.dump(D, open(g, 'w'), ensure_ascii=False)
for k, v in sorted(stats.items(), key=str): print(k, v)
