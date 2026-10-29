"""Apply a round of corrections as ONE commit.

usage: python3 commit_round.py RECORDS.json MESSAGE.txt
  RECORDS.json  a list of text_fixes records (appended to build/text_fixes.json in this order)
  MESSAGE.txt   the commit message: a title line, a blank line, then the list of changes
                (and any attribution lines, such as Co-Authored-By, at its end: none are added)
Every record is first tried on its page (so a record that no longer applies stops the round before
anything is rebuilt), then the site is rebuilt once, committed once, and the column breaks checked."""
import json, subprocess, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
REPO = paths.REPO
TAIL = ("\n\nThese are our corrections, not Sefaria's text and not Jastrow's. Each is a record in\n"
        "build/text_fixes.json with the page, the entry, the text before and after, and the reason.\n")
recs, msg = json.load(open(sys.argv[1])), open(sys.argv[2]).read().rstrip()   # read before leaving the caller's folder
os.chdir(REPO)
tf = json.load(open("build/text_fixes.json"))
json.dump(tf + recs, open("build/text_fixes.json", "w"), ensure_ascii=False, indent=1)
r = subprocess.run([sys.executable, "build/rebuild.py"], capture_output=True, text=True)
if r.returncode:
    json.dump(tf, open("build/text_fixes.json", "w"), ensure_ascii=False, indent=1)   # leave things as they were
    print("REBUILD FAILED, nothing committed\n", r.stderr[-1500:]); sys.exit(1)
print(r.stdout.strip())
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(["git", "commit", "-q", "-m", msg + TAIL], check=True)
c = subprocess.run([sys.executable, "build/checkbreaks.py", "HEAD~1", "HEAD"], capture_output=True, text=True).stdout
print(len(recs), "records |", c.strip().splitlines()[-1])
