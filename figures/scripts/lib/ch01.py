"""Simulation model ch01 (library module, imported by figures/scripts/*.py)."""
import random, math, itertools
def model(H=10,per=12,pgs=4096,size=3,seed=1):
    random.seed(seed)
    sets=set()
    for _ in range(pgs):
        hs=random.sample(range(H),size)
        sets.add(tuple(sorted((h,random.randrange(per)) for h in hs)))
    # probability a random triple of OSDs on 3 distinct hosts is a PG set
    T=math.comb(H,3)*per**3
    return len(sets), T, len(sets)/T
for pgs in [128,1024,4096,16384,65536]:
    n,T,p=model(pgs=pgs); print(pgs,n,T,round(p,4))
# any-3-OSD failure (incl same host) probability: triples total C(120,3)
print(math.comb(120,3))
