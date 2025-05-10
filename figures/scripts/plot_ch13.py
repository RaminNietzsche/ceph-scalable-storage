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
import sys; from gf import *
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch13/'
k,m=4,2; G=rs_matrix(6,4); d=[0x41,0x42,0x43,0x44]; c=matvec(G,d)
fig,ax=plt.subplots(1,3,figsize=(16,6.5),gridspec_kw={'width_ratios':[4,1.3,4]})
A=np.array(G); ax[0].imshow(A>0,cmap='Blues',vmin=0,vmax=1.6)
for i in range(6):
    for j in range(4): ax[0].text(j,i,str(G[i][j]),ha='center',va='center',fontsize=13)
ax[0].set_xticks(range(4)); ax[0].set_xticklabels(['d0','d1','d2','d3']); ax[0].set_yticks(range(6)); ax[0].set_yticklabels(['d0','d1','d2','d3','P0','P1'])
ax[0].set_title('gf_gen_rs_matrix(6,4): identity + rows gen^j\n(gen = 1, then 2), GF(2^8) poly 0x11d')
ax[1].axis('off'); ax[1].text(0.5,0.5,'x\n\n'+'\n'.join('d%d = 0x%02x'%(i,v) for i,v in enumerate(d)),ha='center',va='center',fontsize=13)
ax[2].axis('off')
lines=['P0 = d0 ^ d1 ^ d2 ^ d3 = 0x%02x'%c[4],'P1 = 1*d0 ^ 2*d1 ^ 4*d2 ^ 8*d3 = 0x%02x'%c[5],'   2*0x42 = 0x%02x, 4*0x43 = 0x%02x, 8*0x44 = 0x%02x'%(mul(2,0x42),mul(4,0x43),mul(8,0x44)),'','lose d1 and d3 -> rows {d0, d2, P0, P1}','invert 4x4 in GF(2^8) -> d1 = 0x42, d3 = 0x44','','all 15 two-chunk losses of 4+2 are decodable (MDS)']
for i,l in enumerate(lines): ax[2].text(0,0.9-i*0.1,l,fontsize=12,family='DejaVu Sans Mono')
fig.suptitle('Reed-Solomon (ISA-L reed_sol_van) on one byte column: "ABCD" with k=4, m=2'); fig.tight_layout(); fig.savefig(D+'f09_gfencode.png',dpi=110)
# f10 MDS
fig,ax=plt.subplots(figsize=(16,6.5))
lab=['k=4 m=2','k=21 m=4','k=22 m=4','k=4 m=5','k=8 m=5']; val=[0,0,2,0,6]
cols=['#27ae60','#27ae60','#c0392b','#27ae60','#c0392b']
ax.bar(lab,val,color=cols)
for i,v in enumerate(val): ax.text(i,v+0.1,str(v),ha='center',fontsize=12)
ax.text(2,2.5,'e.g. lose d0, d10, d21, P2',ha='center'); ax.text(4,6.5,'e.g. lose d0, d2, d5, P1, P2',ha='center')
ax.set_ylabel('undecodable loss patterns (<= m lost)'); ax.set_ylim(0,8)
ax.set_title('Vandermonde (gf_gen_rs_matrix) is not MDS for every k, m: ErasureCodeIsa switches to Cauchy when m > 4, or m = 4 and k > 21 (exhaustive check, our script)')
fig.tight_layout(); fig.savefig(D+'f10_mds.png',dpi=110)
# f11 delta
fig,ax=plt.subplots(figsize=(16,6.5)); ax.axis('off')
new=0x5a; Dl=d[2]^new
rows=[('old d2','0x43'),('new d2','0x5a'),('delta = old ^ new','0x%02x'%Dl),('P0 new = P0 ^ 1*delta','0x04 ^ 0x19 = 0x%02x'%(c[4]^Dl)),('P1 new = P1 ^ 4*delta','0xce ^ 0x%02x = 0x%02x'%(mul(4,Dl),c[5]^mul(4,Dl))),('check: full re-encode','P0 = 0x1d, P1 = 0xaa')]
for i,(a,b) in enumerate(rows):
    ax.text(0.05,0.88-i*0.13,a,fontsize=14); ax.text(0.45,0.88-i*0.13,b,fontsize=14,family='DejaVu Sans Mono')
ax.text(0.05,0.05,'4K overwrite of one data shard, FastEC: conventional RMW reads the other k-1 data shards; delta reads old d2 + m parities.  4+2: 3 vs 3 (tie -> delta)   8+3: 7 vs 4 (delta)   2+2: 1 vs 3 (conventional)',fontsize=11,color='#7d3c98')
ax.set_title('parity delta update (ErasureCodeIsaDefault::encode_delta / apply_delta -> ec_encode_data_update): only the changed shard and the parities are touched')
fig.tight_layout(); fig.savefig(D+'f11_delta.png',dpi=110)
# f12 repair
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
for a,(ttl,items) in zip(ax,[('k=4 m=2 (chunk = 1 unit)',[('RS 4+2',4,1.5),('LRC 4+2 l=3',3,2.0),('CLAY 4+2 d=5',2.5,1.5)]),('k=8 m=4',[('RS 8+4',8,1.5),('LRC 8+4 l=4',4,15/8),('CLAY 8+4 d=11',2.75,1.5)])]):
    names=[x[0] for x in items]; rd=[x[1] for x in items]; ov=[x[2] for x in items]
    b=a.bar(names,rd,color=['#5dade2','#f5b041','#58d68d'])
    for i,(r,o) in enumerate(zip(rd,ov)): a.text(i,r+0.1,'read %.2f chunks\nraw overhead %.3gx'%(r,o),ha='center')
    a.set_ylim(0,max(rd)*1.35); a.set_ylabel('data read to rebuild ONE lost chunk (chunks)'); a.set_title(ttl)
fig.suptitle('repair traffic: RS reads k chunks; LRC reads l chunks (local group); CLAY reads d x chunk / (d-k+1) sub-chunks')
fig.tight_layout(); fig.savefig(D+'f12_repair.png',dpi=110)
