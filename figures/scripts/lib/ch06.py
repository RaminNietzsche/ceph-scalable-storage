"""Simulation model ch06 (library module, imported by figures/scripts/*.py)."""
from rj import *
import collections, math
names=['file_%05d'%i for i in range(100000)]
H=[rj(n) for n in names]
# 3-bit frags
fr=[frag_make(3,i<<21) for i in range(8)]
print([hex(f) for f in fr])
c=collections.Counter(next(i for i,f in enumerate(fr) if frag_contains(f,h)) for h in H)
print('8 frags',sorted(c.items()))
for n in ['file_00042','report.pdf','IMG_0001.JPG']:
    h=rj(n); i=next(i for i,f in enumerate(fr) if frag_contains(f,h))
    print(n,hex(h),'bits23-21=',(h>>21)&7,'frag',hex(fr[i]))
# growth sim: entries inserted sequentially; split when frag size>10000 into 8 (ignore delay)
leaves={frag_make(0,0):0}
def leaf_of(h):
    for f in leaves:
        if frag_contains(f,h): return f
events=[]
assign={}
for idx,h in enumerate(H):
    f=leaf_of(h); leaves[f]+=1
    if leaves[f]>10000:
        b=f>>24; v=f&0xffffff
        kids=[frag_make(b+3, v|(i<<(24-b-3))) for i in range(8)]
        del leaves[f]
        for k in kids: leaves[k]=0
        for h2 in H[:idx+1]:
            if frag_contains(f,h2):
                leaves[leaf_of(h2)]+=1
        events.append((idx+1,len(leaves)))
print('splits at (entries,leaves):',events)
print('final leaves',len(leaves),min(leaves.values()),max(leaves.values()))
# decay
T=5; k=math.log(.5)/T
for r in [1000,1386,1500,3000,5000]:
    eq=r/(-k)
    t=None
    if eq>10000: t=-T*math.log2(1-10000/eq)
    print(r,'eq',round(eq),'t_to_10000', None if t is None else round(t,2))
for r in [3466,4000,8000]:
    eq=r/(-k); t=-T*math.log2(1-25000/eq) if eq>25000 else None
    print('rd',r,round(eq),t and round(t,2))
# striping
def loc(off,su,sc,os):
    bn=off//su; sn=bn//sc; pos=bn%sc; spo=os//su; osn=sn//spo; on=osn*sc+pos
    return on,(sn%spo)*su+off%su
MiB=1<<20
for off in [0,1*MiB,4*MiB,9*MiB,9*MiB+12345]:
    print(off, loc(off,4*MiB,1,4*MiB), loc(off,1*MiB,4,4*MiB))
print('%x.%08x'%(0x10000000000,2), '%x.%08x'%(0x10000000005,frag_make(3,5<<21)))
