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
m=json.load(open('figures/data/ch08_move.json'));c=json.load(open('figures/data/ch08_move_cls.json'))
# f11 add host
a=m['straw2']['add_host']
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
vals=[a['ideal'],a['to_new'],a['moved']-a['to_new']]
labs=['ideal: 24576 x 12/132','replicas moved to new host10\n(osd.120-131)','replicas moved between OLD OSDs\n(leaf redrawn with new r)']
b=ax.barh(labs,vals,color=['#95a5a6','#27ae60','#e67e22'])
for i,v in enumerate(vals): ax.text(v+20,i,f'{v:.0f}  ({100*v/a["total"]:.2f}% of {a["total"]} replicas)',va='center')
ax.set_xlim(0,3200);ax.invert_yaxis();ax.set_xlabel('replica placements that change')
ax.set_title('Adding an 11th host (12 OSDs) to 10x12 OSDs, straw2, pool size 3, pg_num 8192 (osdmaptool, Ceph 18.2.7)')
plt.tight_layout();plt.savefig('figures/ch08/f07_addhost.png')
# f12 reweight
fig,axs=plt.subplots(1,2,figsize=(16,6.5),dpi=110,sharey=True)
fs=['0.5','0.8','1.2','1.5','2.0']
for ax,alg in zip(axs,['straw2','straw']):
    d=c[alg];x=np.arange(len(fs))
    o5=[d[f]['osd5'] for f in fs];h0=[d[f]['host0_other'] for f in fs];un=[d[f]['unrelated'] for f in fs]
    ax.bar(x,o5,color='#2e86c1',label='to/from osd.5 itself')
    ax.bar(x,h0,bottom=o5,color='#f5b041',label='other OSDs of host0 (host weight changed)')
    ax.bar(x,un,bottom=np.add(o5,h0),color='#c0392b',label='unrelated hosts (position/r shift)')
    for i in range(len(fs)): ax.text(i,o5[i]+h0[i]+un[i]+5,str(o5[i]+h0[i]+un[i]),ha='center')
    ax.set_xticks(x);ax.set_xticklabels([f'1.0 -> {f}' for f in fs]);ax.set_title(f'bucket alg = {alg}');ax.set_xlabel('CRUSH weight of osd.5')
axs[0].set_ylabel('replica placements that change (of 24576)');axs[0].legend()
fig.suptitle('Changing one OSD weight: what moves (10 hosts x 12 OSDs, size 3, pg_num 8192; osdmaptool --test-map-pgs-dump)')
plt.tight_layout();plt.savefig('figures/ch08/f08_reweight.png')
