"""Simulation model ch05 (library module, imported by figures/scripts/*.py)."""
from rgw import h
import collections
# datalog shard for bucket 'photos' with 11 index shards
b='photos'; H=h(b); print('h(photos)',H, H%128)
print([ (H+max(s,0))%128 for s in range(11)])
for b in ['photos','logs','backup-2026']:
    print(b,h(b)%128)
# mdlog: hash of "section:key" %64
for k in ['user:alice','bucket:photos','bucket.instance:photos:a1b2c3d4.4567.1']:
    print(k,h(k),h(k)%64)
# distribution of 1000 buckets "bucket-%04d" over 64 mdlog shards
c=collections.Counter(h('bucket:bucket-%04d'%i)%64 for i in range(1000))
print('md min max',min(c.values()),max(c.values()),len(c))
# window sim: writes every 10ms on one bucket shard from t=0..120s, window 30, renew every 22
W=30; R=W*3//4; print('renew',R)
entries=[]; exp=-1; pending_renew=False; t=0.0; nexttick=R
writes=[i*0.01 for i in range(12000)]
i=0
events=[]
while i<len(writes):
    t=writes[i]
    while nexttick<=t:
        if pending_renew:
            entries.append(nexttick); exp=nexttick+W; pending_renew=False
        nexttick+=R
    if t<exp: pending_renew=True
    else: entries.append(t); exp=t+W
    i+=1
print('writes',len(writes),'entries',entries)
# sparse: writes at 0,5,40,41,100
entries=[]; exp=-1; pr=False; nexttick=R
for t in [0,5,40,41,100]:
    while nexttick<=t:
        if pr: entries.append(nexttick); exp=nexttick+W; pr=False
        nexttick+=R
    if t<exp: pr=True
    else: entries.append(t); exp=t+W
while nexttick<=130:
    if pr: entries.append(nexttick); exp=nexttick+W; pr=False
    nexttick+=R
print('sparse',entries)
