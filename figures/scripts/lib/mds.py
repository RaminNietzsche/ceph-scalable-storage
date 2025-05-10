"""Simulation model mds (library module, imported by figures/scripts/*.py)."""
from gf import *
import itertools,sys
def singular(M):
    try: invert(M); return False
    except StopIteration: return True
def check(k,m,limit=None):
    G=rs_matrix(k+m,k); n=0; ex=None
    # only need to test patterns where m data chunks lost and replaced by parity rows: choose lost data set L (|L|<=m) and parity subset
    for e in range(1,m+1):
        for L in itertools.combinations(range(k),e):
            for P in itertools.combinations(range(k,k+m),e):
                rows=[r for r in range(k) if r not in L]+list(P)
                if singular([G[r] for r in rows]):
                    n+=1; ex=ex or (L,P)
    return n,ex
for k,m in [(21,4),(22,4),(4,5),(8,5)]:
    print(k,m,check(k,m))
