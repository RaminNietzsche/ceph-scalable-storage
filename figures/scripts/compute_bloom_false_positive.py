#!/usr/bin/env python3
"""Small verification calculator used while writing the chapter text.

Migrated from the v1.0-v1.4 working tree; paths are repository-relative.
Run from anywhere: the script changes into the repository root first.
"""
import os as _os, sys as _sys
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
_os.chdir(_ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, 'figures', 'scripts', 'lib'))
CEPH_CONF = _os.environ.get('CEPH_CONF', '/etc/ceph/ceph.conf')
import math,random
def std(b,k): return (1-math.exp(-k/b))**k
def cl(b,k,L=512):
    kp=L/b; sd=math.sqrt(kp)
    return (std(L/(kp+sd),k)+std(L/(kp-sd),k))/2
def probes(mb):
    t=[(2080,1),(3580,2),(5100,3),(6640,4),(8300,5),(10070,6),(11720,7),(14001,8),(16050,9),(18300,10),(22001,11),(25501,12)]
    for lim,p in t:
        if mb<=lim: return p
    return 24 if mb>50000 else (mb-1)//2000-1
for b in (10,16,20):
    k=probes(b*1000); fp=cl(b,k); fpr=fp+ (1-math.exp(-1e6*2**-64)) - fp*(1-math.exp(-1e6*2**-64))
    print(b,'probes',k,'cl %.3e'%fp,'std_opt %.3e'%std(b,int(b*0.69)),'std same k %.3e'%std(b,k))
# skiplist sim
random.seed(7)
n=160000
H=[]
for i in range(n):
    h=1
    while h<12 and random.random()<0.25: h+=1
    H.append(h)
print('max height',max(H),'count h>=k',[sum(1 for x in H if x>=k) for k in range(1,11)])
print('avg height',sum(H)/n,'bytes ptrs avg',8*sum(H)/n)
