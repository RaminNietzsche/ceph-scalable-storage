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
import matplotlib.pyplot as plt, numpy as np
plt.rcParams['font.family']='DejaVu Sans'
rs=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[1,1,1,1],[1,2,4,8]]
ca=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[0x47,0xa7,0x7a,0xba],[0xa7,0x47,0xba,0x7a]]
D=[0x37,0x5c,0xa1,0x0f]
fig,axs=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
for ax,M,name,P in ((axs[0],rs,'gf_gen_rs_matrix (technique=reed_sol_van)',['C5','49']),(axs[1],ca,'gf_gen_cauchy1_matrix (technique=cauchy)',['D1','09'])):
    A=np.array(M,dtype=float); col=np.where(np.arange(6)[:,None]<4,0.15,0.55)+0*A
    ax.imshow(col,cmap='Blues',vmin=0,vmax=1,aspect='auto')
    for i in range(6):
        for j in range(4):
            ax.text(j,i,'0x%02X'%M[i][j],ha='center',va='center',fontsize=15,weight='bold' if i>=4 else 'normal')
    ax.set_xticks(range(4)); ax.set_xticklabels(['D0=0x37','D1=0x5C','D2=0xA1','D3=0x0F'],fontsize=13)
    ax.set_yticks(range(6)); ax.set_yticklabels(['row0 -> D0','row1 -> D1','row2 -> D2','row3 -> D3','row4 -> P = 0x'+P[0],'row5 -> Q = 0x'+P[1]],fontsize=13)
    ax.set_title(name,fontsize=15)
    ax.axhline(3.5,color='k',lw=2)
fig.suptitle('ISA-L encode matrices for k=4, m=2 over GF(2^8), poly 0x11D  (identity on top, parity rows below)',fontsize=16)
plt.tight_layout(); plt.savefig('f06_matrices.png')
# clay grid
q,t=2,3; S=8
def rep(n):
    y=n//q; x=n%q; seq=q**(t-1-y); num=q**y; idx=x*seq; out=[]
    for _ in range(num):
        out+=list(range(idx,idx+seq)); idx+=q*seq
    return out
fig,axs=plt.subplots(1,3,figsize=(16,6.5),dpi=110)
for ax,lost in zip(axs,(0,2,5)):
    G=np.zeros((6,S))
    r=rep(lost)
    for n in range(6):
        for s in range(S):
            if n==lost: G[n,s]=3
            elif s in r: G[n,s]=2
            else: G[n,s]=0
    from matplotlib.colors import ListedColormap
    ax.imshow(G,cmap=ListedColormap(['#F1F1F1','#FFFFFF','#9EC5FE','#F4A3A3']),vmin=0,vmax=3,aspect='auto')
    for n in range(6):
        for s in range(S):
            ax.text(s,n,str(s),ha='center',va='center',fontsize=12)
    ax.set_xticks(range(S)); ax.set_xlabel('sub-chunk index',fontsize=13)
    ax.set_yticks(range(6)); ax.set_yticklabels([f'node {n} (x={n%q},y={n//q})' for n in range(6)],fontsize=12)
    ax.set_title(f'lost node {lost}: helpers read {r}',fontsize=13)
    ax.set_xticks(np.arange(-.5,S,1),minor=True); ax.set_yticks(np.arange(-.5,6,1),minor=True); ax.grid(which='minor',color='w',lw=2)
fig.suptitle('Clay k=4 m=2 d=5: q=d-k+1=2, t=(k+m)/q=3, sub_chunk_no=q^t=8. Each of d=5 helpers sends 4/8 of its chunk (blue): 2.5 chunks total vs 4 for RS',fontsize=14)
plt.tight_layout(); plt.savefig('f10_clay.png')
