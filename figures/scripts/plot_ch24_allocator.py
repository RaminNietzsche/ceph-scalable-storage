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
import json,math,matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt,numpy as np
plt.rcParams['font.family']='DejaVu Sans'
S=[('empty','A: after earlier test pools were deleted (score 0.0163)','#95a5a6'),('full','B: + 6000 x 64 KiB objects written (score 0.0167)','#2e86c1'),('half','C: + random 51% of them deleted (score 0.0215)','#c0392b')]
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110);bins=np.arange(12,32);w=0.27
for i,(n,l,c) in enumerate(S):
    ex=[int(e['length'],16) for e in json.load(open(f'figures/data/alloc_{n}.json'))['extents']]
    cnt=np.zeros(len(bins));by=np.zeros(len(bins))
    for x in ex: k=int(math.log2(x))-12;cnt[k]+=1;by[k]+=x
    a.bar(bins+(i-1)*w,cnt,w,color=c,label=f'{l}, {len(ex)} extents')
    b.bar(bins+(i-1)*w,by/2**30,w,color=c,label=l)
a.set_yscale('log');a.set_xticks(bins[::2]);a.set_xticklabels([f'{2**k//1024}K' if k<20 else f'{2**(k-20)}M' if k<30 else f'{2**(k-30)}G' for k in bins[::2]]);a.set_xlabel('free extent size bin [2^k, 2^(k+1))');a.set_ylabel('free extents (log)');a.legend(fontsize=8);a.set_title('How many free extents')
b.set_xticks(bins[::2]);b.set_xticklabels(a.get_xticklabels());b.set_xlabel('free extent size bin');b.set_ylabel('free GiB in bin');b.set_title('Where the free bytes are')
fig.suptitle('Real free-space map of osd.0 (10 GiB BlueStore, hybrid allocator, min_alloc 4 KiB): ceph daemon osd.0 bluestore allocator dump/score block, Ceph 18.2.7')
plt.tight_layout();plt.savefig('figures/ch24/f10_freemap.png')
