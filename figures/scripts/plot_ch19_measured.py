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
u=json.load(open('figures/data/upmap_real.json'))
fig,axs=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
for ax,pg in zip(axs,['1024','8192']):
    b=u[pg]['before'];a=u[pg]['after'];lo=min(b+a)-2;hi=max(b+a)+2;bins=np.arange(lo,hi+1)
    ax.hist(b,bins=bins,color='#e67e22',alpha=.75,label=f'CRUSH only: min {min(b)} max {max(b)} sd {np.std(b):.2f}')
    ax.hist(a,bins=bins,color='#2e86c1',alpha=.85,label=f'after upmap: min {min(a)} max {max(a)} sd {np.std(a):.2f}')
    ax.set_title(f'pg_num {pg}: {u[pg]["entries"]} pg-upmap-items, {u[pg]["pairs"]} replica remaps ({100*u[pg]["pairs"]/(3*int(pg)):.1f}% of replicas)')
    ax.set_xlabel('PG replicas per OSD');ax.set_ylabel('number of OSDs');ax.legend()
fig.suptitle('osdmaptool --upmap --upmap-deviation 1 on 120 OSDs (10 hosts x 12), size 3, Ceph 18.2.7')
plt.tight_layout();plt.savefig('figures/ch19/f08_upmap.png')
s=json.load(open('figures/data/split_real.json'))
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
ks=sorted(s,key=int);x=np.arange(len(ks))
h=np.array([s[k]['hist'] for k in ks],float);h=h/h.sum(1,keepdims=True)*100
cols=['#27ae60','#f1c40f','#e67e22','#c0392b']
bot=np.zeros(len(ks))
for i in range(4):
    a.bar(x,h[:,i],bottom=bot,color=cols[i],label=f'{i} of 3 replicas on new OSDs');bot+=h[:,i]
for i,k in enumerate(ks): a.text(i,101,f'{100*s[k]["moved_frac"]:.1f}%\nmoved',ha='center',fontsize=8)
a.set_xticks(x);a.set_xticklabels([f'{int(k)//2}\n->{k}' for k in ks],fontsize=8);a.set_ylim(0,112);a.set_ylabel('% of child PGs')
a.set_title('Doubling pg_num (=pgp_num): where child PGs land (osdmaptool, 120 OSDs)');a.legend(loc='lower left',fontsize=8)
# controller simulation (DaemonServer::adjust_pgs), assume backfill finishes between ticks
pg,pgp,T=1024,1024,2048;mm=0.05;steps=[(0,pg,pgp)];t=0
while pgp<T:
    t+=1
    if pg<T and pg-pgp<128: pg+=min(128-(pg-pgp),T-pg)
    tgt=min(pg,T)
    if tgt>pgp and pgp!=pg:
        room=min(mm-0,mm/2);est=max(int(pg*room),1);pgp=min(tgt,pgp+est)
    steps.append((t,pg,pgp))
st=np.array(steps)
b.step(st[:,0],st[:,1],where='post',label='pg_num (+<=128 gap, mgr_max_pg_num_change)',color='#8e44ad')
b.step(st[:,0],st[:,2],where='post',label='pgp_num (+pg_num x min(0.05-misplaced, 0.025))',color='#2e86c1')
b.set_xlabel('controller ticks that change pgp_num (each waits for misplaced <= 5%)');b.set_ylabel('PGs')
b.set_title(f'mgr pg_num controller 1024 -> 2048: {len(steps)-1} pgp steps (model of adjust_pgs, ideal backfill)');b.legend()
plt.tight_layout();plt.savefig('figures/ch19/f09_split.png')
print(len(steps)-1, steps[:4])
