"""Simulation model rgw (library module, imported by figures/scripts/*.py)."""
import math,bisect,re
def h(s):
    x=0
    for ch in s.encode(): x=(x+(ch<<4)+(ch>>4))*11 & 0xffffffff
    return x
def shard(k,n):
    sid=h(k); sid2=(sid ^ ((sid&0xff)<<24))&0xffffffff
    return sid2%7877%n if n<=7877 else sid2%65521%n
import json as _json, os as _os
PR=_json.load(open(_os.path.join(_os.path.dirname(__file__),'..','..','data','rgw_reshard_primes.json')))['primes']
def nearest(n):
    k=bisect.bisect_left(PR,n); return PR[k] if k<len(PR) else n
def calc(num_objs,cur,ms=False,maxd=1999,maxo=100000):
    mino=min(10000,math.ceil(maxo/100))
    if cur<maxd and num_objs>cur*maxo: pass
    elif cur>11 and num_objs<cur*mino: pass
    else: return cur
    m=8 if ms else 2
    c=max(11,min(maxd,num_objs*m//maxo))
    if c==cur: return cur
    c=nearest(c); return min(maxd,max(c,11))
def per_shard(n,s):
    if s==0: return 0
    return max(8,1+int(n//s + math.sqrt(2*n*math.log(s)/s)))
