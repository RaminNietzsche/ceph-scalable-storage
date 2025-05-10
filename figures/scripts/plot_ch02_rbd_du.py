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
import json,matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt,numpy as np
plt.rcParams['font.family']='DejaVu Sans'
d=json.load(open('figures/data/du_real.json'))
written={'A_100x1K':100*1024,'B_1000x1K':1000*1024,'C_seq256M':256<<20,'D_2000x4K_rand2G':2000*4096}
lab={'A_100x1K':'A: 100 x 1 KiB\n(offset 0 of 100 objs)','B_1000x1K':'B: 1000 x 1 KiB\n(offset 0 of 1000 objs)','C_seq256M':'C: 256 MiB\nsequential','D_2000x4K_rand2G':'D: 2000 x 4 KiB random\nin first 2 GiB (503 objs)'}
ks=list(d);x=np.arange(len(ks));w=0.27
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
vals=[[written[k] for k in ks],[d[k]['exact'] for k in ks],[d[k]['default'] for k in ks]]
names=['bytes actually written','rbd du --exact','rbd du (default, fast-diff)'];cols=['#7f8c8d','#2e86c1','#e67e22']
for i,(v,n,c) in enumerate(zip(vals,names,cols)):
    b=ax.bar(x+(i-1)*w,v,w,label=n,color=c)
    for xi,vi in zip(x+(i-1)*w,v): ax.text(xi,vi*1.15,f'{vi/2**20:.2f} MiB' if vi<2**30 else f'{vi/2**30:.2f} GiB',ha='center',fontsize=8,rotation=90,va='bottom')
ax.set_yscale('log');ax.set_ylim(5e4,5e10);ax.set_xticks(x);ax.set_xticklabels([lab[k] for k in ks])
ax.set_ylabel('USED (bytes, log)');ax.legend(loc='upper left')
ax.set_title('Measured on a 3-OSD test cluster, Ceph 18.2.7 (Reef), 10 GiB images, 4 MiB objects, features=61')
plt.tight_layout();plt.savefig('figures/ch02/f10_du.png')
