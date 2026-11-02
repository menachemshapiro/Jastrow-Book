"""Apply the user's choices from headwords_2018_2026.html (its Export, jastrow-hw-2018-2026.json) to
build/headwords_scan.json, rebuild, and commit if the rebuild succeeds.
usage: python3 build/apply_hw_choices.py ~/Downloads/jastrow-hw-2018-2026.json"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
ch = json.load(open(os.path.expanduser(sys.argv[1])))
f = os.path.join(paths.REPO, "build", "headwords_scan.json")
d = json.load(open(f))
n = {"2018": 0, "2026": 0}
for eid, m in ch.items():
    v = m.get("v")
    if v not in ("2018", "2026"): continue          # "neither" and unmarked: a record later
    for k in ("2018", "2026"):
        if eid in d[k]: d[k].remove(eid)
    d[v].append(eid); n[v] += 1
for k in ("2018", "2026"): d[k] = sorted(set(d[k]))
json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)
print("chosen:", n, "| neither:", [e for e, m in ch.items() if m.get("v") == "neither"])
r = subprocess.run([sys.executable, os.path.join(paths.REPO, "build", "rebuild.py")])
if r.returncode: sys.exit("REBUILD FAILED: nothing committed (git checkout build/headwords_scan.json to undo)")
os.chdir(paths.REPO)
subprocess.run(["git", "add", "build/headwords_scan.json", "data"], check=True)
subprocess.run(["git", "commit", "-q", "-m", "Headwords: the user's choices of 2018 or 2026 forms on the scan (%d 2018, %d 2026)" % (n["2018"], n["2026"])], check=True)
print(subprocess.run([sys.executable, "build/checkbreaks.py", "HEAD~1", "HEAD"], capture_output=True, text=True).stdout.strip().splitlines()[-1])
