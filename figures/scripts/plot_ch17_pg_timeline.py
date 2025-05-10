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
d=json.load(open('figures/data/pgstates.json'));log=d['log'];ev=d['events']
def grp(s):
    if s=='active+clean': return 'active+clean'
    if 'stale' in s: return 'stale (no fresh report)'
    if 'peering' in s: return 'peering'
    if 'undersized' in s: return 'active+undersized+degraded'
    if 'recovering' in s: return 'active+recovering(+degraded)'
    if 'recovery_wait' in s: return 'active+recovery_wait+degraded'
    return 'other'
G=['active+clean','active+recovering(+degraded)','active+recovery_wait+degraded','peering','stale (no fresh report)','active+undersized+degraded','other']
col=['#27ae60','#2e86c1','#85c1e9','#f1c40f','#95a5a6','#e74c3c','#000']
t=[x[0] for x in log];Y=np.zeros((len(G),len(log)))
for j,(_,c) in enumerate(log):
    for s,n in c.items(): Y[G.index(grp(s)),j]+=n
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
ax.stackplot(t,Y,labels=G,colors=col,step='post')
for te,n in ev: ax.axvline(te,color='k',ls='--');ax.text(te+0.5,33,n,fontsize=10)
ax.set_ylim(0,36);ax.set_xlim(0,max(t));ax.set_xlabel('seconds');ax.set_ylabel('PGs (pool t17, 32 PGs, size 2)')
ax.legend(loc='lower left',fontsize=9,ncol=2)
ax.set_title('Measured PG states: 3 BlueStore OSDs, 300 x 4 MiB objects, Ceph 18.2.7, sampled with ceph pg dump pgs_brief every ~1 s')
plt.tight_layout();plt.savefig('figures/ch17/f08_pgtimeline.png')
