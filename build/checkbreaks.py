"""Compare the column breaks of two commits and list the pages whose break moved.
usage: python3 build/checkbreaks.py A B      (e.g. HEAD~1 HEAD, or main oct29)"""
import json,re,html,subprocess,sys,os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def txt(h): return html.unescape(re.sub(r'<[^>]+>','',h))
def load(ref):
    g=lambda p: json.loads(subprocess.check_output(['git','show',ref+':'+p]))
    P=g('data/pages.json')['pages']; ch={}
    out=[]
    for i,pg in enumerate(P):
        k=i//10
        if k not in ch: ch[k]=g('data/c%03d.json'%k)
        x=ch[k][i%10]; out.append((pg[0],pg[6],''.join(x) if isinstance(x,list) else x))
    return out
A=load(sys.argv[1]); B=load(sys.argv[2])
bad=0
for (l,oa,ha),(_,ob,hb) in zip(A,B):
    if ha==hb: continue
    # compare words around break by plain text count (break offset assumed in plain text)
    ta,tb=txt(ha),txt(hb)
    sa=ta[oa:oa+25].split(); sb=tb[ob:ob+25].split()
    if not oa: continue
    if sa[:2]!=sb[:2] and sa[:1]!=sb[:1]: bad+=1; print(l,repr(ta[oa-12:oa]),repr(ta[oa:oa+12]),'|',repr(tb[ob-12:ob]),repr(tb[ob:ob+12]))
print('changed pages',sum(a[2]!=b[2] for a,b in zip(A,B)),'moved',bad)
