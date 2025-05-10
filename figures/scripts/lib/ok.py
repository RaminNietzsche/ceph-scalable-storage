"""Simulation model ok (library module, imported by figures/scripts/*.py)."""
import random
def mk(hosts=4,per=3,size=3,pgs=128,seed=1):
    r=random.Random(seed); H={h:[h*per+i for i in range(per)] for h in range(hosts)}
    P=[]
    for p in range(pgs):
        hs=r.sample(range(hosts),size); P.append([r.choice(H[h]) for h in hs])
    return H,P
def ok(S,P,minsize):
    bad=sum(1 for a in P if any(o in S for o in a) and len([o for o in a if o not in S])<minsize)
    return bad==0,bad
def maximize(start,H,P,minsize,mx=16):
    S={start}; host=[h for h in H if start in H[h]][0]; log=[]
    for level,children in (('host',sorted(H[host])),('root',sorted(o for h in H for o in H[h]))):
        failed=0
        for o in children:
            if o in S: continue
            S.add(o); g,b=ok(S,P,minsize)
            if not g: S.discard(o); failed+=1; log.append((level,o,'reject',b)); continue
            log.append((level,o,'add',0))
            if len(S)==mx: return S,log
        if failed: return S,log
    return S,log
if __name__=='__main__':
    H,P=mk(); S,log=maximize(0,H,P,2); print(sorted(S)); print(log)
    H,P=mk(hosts=6,per=2,size=6); S,log=maximize(0,H,P,5); print(sorted(S), log[:4])
    H,P=mk(hosts=6,per=2,size=6); S,log=maximize(0,H,P,4); print('min_size=k',sorted(S), log[:6])
