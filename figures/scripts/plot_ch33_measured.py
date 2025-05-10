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
d=json.load(open('figures/data/mem33.json'))
w=[s['writes'] for s in d]
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
a.plot(w,[max(s['log_sizes']) for s in d],'o-',color='#c0392b',label='max log_size over the 32 PGs')
a.plot(w,[np.mean(s['log_sizes']) for s in d],'s-',color='#2e86c1',label='mean log_size')
for n,c in [(33,'#7f8c8d'),(38,'#bdc3c7'),(25,'#95a5a6')]:
    a.axhline(30000/n,ls='--',color=c);a.text(2000,30000/n+15,f'30000 / {n} PGs = {30000//n}',fontsize=8)
a.axvline(120000,color='k',ls=':');a.text(122000,200,'switch: overwrite 1000 objs -> create new objs',fontsize=8)
a.set_xlabel('128-byte writes to pool m33 (size 1, 32 PGs)');a.set_ylabel('pg log entries per PG');a.legend(loc='center right');a.set_title('pg log length: get_target_pg_log_entries(), target set to 30000/OSD')
cols=['#c0392b','#2e86c1','#27ae60']
for i in range(3):
    b.plot(w,[s['osd'][str(i)]['osd_pglog'][1]/2**20 for s in d],'-',color=cols[i],label=f'osd.{i} osd_pglog')
    b.plot(w,[s['osd'][str(i)]['bluestore_cache_onode'][1]/2**20 for s in d],'--',color=cols[i],label=f'osd.{i} bluestore_cache_onode')
b.axvline(120000,color='k',ls=':');b.set_xlabel('writes');b.set_ylabel('MiB (dump_mempools)');b.legend(fontsize=8,ncol=2);b.set_title('mempool MiB: pg log grows slowly (dups); onode cache grows with new objects')
fig.suptitle('Measured on 3 BlueStore OSDs, Ceph 18.2.7 test cluster: ceph daemon osd.N dump_mempools + ceph pg ls-by-pool -f json every 10k writes')
plt.tight_layout();plt.savefig('figures/ch33/f09_pglogmem.png')
last=d[-1]['osd']['0']
K=['bluestore_cache_onode','osd_pglog','osdmap','bluestore_blob','bluestore_shared_blob','bluestore_inline_bl','bluestore_alloc','bluefs','bluestore_extent','bluestore_cache_other','bluestore_cache_meta']
v=[last[k][1]/last[k][0] for k in K]
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
bb=ax.barh(K,v,color='#8e44ad');ax.invert_yaxis()
for i,(k,x) in enumerate(zip(K,v)): ax.text(x+5,i,f'{x:.1f} B/item  ({last[k][0]} items, {last[k][1]/2**20:.1f} MiB)',va='center',fontsize=9)
ax.set_xlim(0,900);ax.set_xlabel('bytes per mempool item on osd.0 (bytes / items)')
ax.set_title('Real per-item cost from dump_mempools (osd.0 after 180k writes): an onode in cache ~680 B, an AVL free-range node 80 B, a pg log item ~380 B')
plt.tight_layout();plt.savefig('figures/ch33/f10_itemcost.png')
