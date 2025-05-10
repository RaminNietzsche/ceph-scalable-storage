#!/usr/bin/env python3
"""Draw figure(s) for the chapter named in the file name.

Migrated from the v1.0-v1.4 working tree; paths are repository-relative.
Run from anywhere: the script changes into the repository root first.
"""
import os as _os, sys as _sys
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
_os.chdir(_ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, 'figures', 'scripts', 'lib'))
CEPH_CONF = _os.environ.get('CEPH_CONF', '/etc/ceph/ceph.conf')
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch02/'
K=1024; M=1024*K; OS=4*M; G=64*K
def prune(off,ln):
    out=[]; end=off+ln; o=off
    while o<end:
        obj=o//OS; oo=o%OS; l=min(end-o,OS-oo)
        a=-(-oo//G)*G; b=((oo+l)//G)*G
        if a>=b: out.append((obj,oo,l,None,None,'skipped'))
        else:
            if a==0 and b==OS: act='remove'
            elif b==OS: act='truncate @%dK'%(a//K)
            else: act='zero %dK..%dK'%(a//K,b//K)
            out.append((obj,oo,l,a,b,act))
        o+=l
    return out
cases=[('discard 10K @ 100K',100*K,10*K),('discard 200K @ 100K',100*K,200*K),('discard 1M @ 3.5M',3584*K,1*M),('discard 4M @ 2M',2*M,4*M),('discard 8M @ 4M',4*M,8*M)]
fig,ax=plt.subplots(figsize=(16,6.5))
for i,(name,off,ln) in enumerate(cases):
    y=len(cases)-1-i
    for obj in range(3):
        ax.add_patch(Rectangle((obj*4.2,y),4,0.6,fill=False,ec='gray'))
    ax.add_patch(Rectangle((off/M+ (off//OS)*0.2,y+0.62),ln/M+((off+ln-1)//OS-off//OS)*0.2,0.12,color='#7f8c8d'))
    for obj,oo,l,a,b,act in prune(off,ln):
        x0=obj*4.2
        if a is None:
            ax.add_patch(Rectangle((x0+oo/M,y),l/M,0.6,color='#d5d8dc',hatch='//')); txt='skipped'
        else:
            c={'r':'#c0392b','t':'#e67e22','z':'#2471a3'}[act[0]]
            ax.add_patch(Rectangle((x0+a/M,y),(b-a)/M,0.6,color=c))
        ax.text(x0+2,y+0.3,act,ha='center',va='center',fontsize=9,color='k',bbox=dict(fc='white',ec='none',alpha=0.7))
    ax.text(-0.3,y+0.3,name,ha='right',va='center',fontsize=10)
for obj in range(3): ax.text(obj*4.2+2,len(cases)+0.1,'rbd_data.<id>.%016x'%obj,ha='center',fontsize=9)
ax.set_xlim(-5,12.8); ax.set_ylim(-0.3,len(cases)+0.5); ax.axis('off')
ax.set_title('librbd discard with 4 MiB objects and rbd_discard_granularity_bytes 64K (grey bar = requested range): red remove, orange truncate, blue zero, hatched skipped')
fig.tight_layout(); fig.savefig(D+'f09_discard.png',dpi=110)
# f10 du
import random
random.seed(3)
pats=[('100 x 1 KiB random writes\n(10 GiB image)',100*4*M,100*K),('fstrim-ed ext4, 2 GiB files\nin 4 MiB objects',2*1024*M+12*M,2*1024*M),('VM image: 30 GiB written\nsequentially',30*1024*M,30*1024*M),('1 KiB metadata per 4 MiB\nfor 1000 objects',1000*4*M,1000*K)]
fig,ax=plt.subplots(figsize=(16,6.5))
import numpy as np
x=np.arange(len(pats))
ax.bar(x-0.2,[p[1]/M for p in pats],0.4,color='#e67e22',label='rbd du (default, whole objects via fast-diff)')
ax.bar(x+0.2,[p[2]/M for p in pats],0.4,color='#2471a3',label='rbd du --exact (extent-level)')
for i,p in enumerate(pats):
    ax.text(i-0.2,p[1]/M*1.15,'%.0f MiB'%(p[1]/M),ha='center',fontsize=9); ax.text(i+0.2,p[2]/M*1.15,('%.2f MiB'%(p[2]/M)) if p[2]<M*10 else '%.0f MiB'%(p[2]/M),ha='center',fontsize=9)
ax.set_yscale('log'); ax.set_xticks(x); ax.set_xticklabels([p[0] for p in pats]); ax.set_ylabel('USED reported (MiB, log)')
ax.set_title('rbd du counts every existing object as a whole object unless --exact (synthetic workloads; actual raw use also x size and BlueStore min_alloc)')
ax.legend(); fig.tight_layout(); fig.savefig(D+'f10_du.png',dpi=110)
