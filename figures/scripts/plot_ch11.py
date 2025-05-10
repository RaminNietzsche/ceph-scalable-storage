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
import matplotlib.pyplot as plt, numpy as np, hashlib, random, sys
from matplotlib.patches import Rectangle, FancyBboxPatch
from ok import mk, maximize
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch11/'
hosts=['ceph-0%d'%i for i in range(1,7)]
svcs=['mon','mgr','mds.cephfs','rgw.s3','crash']
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
cols=plt.cm.Set2(np.linspace(0,1,6))
for r,s in enumerate(svcs):
    seed=int(hashlib.sha1(s.encode()).hexdigest(),16)%(2**32); f=sorted(hosts); random.Random(seed).shuffle(f)
    y=len(svcs)-1-r
    ax.text(-0.2,y+0.4,f'{s}\nseed={seed}',ha='right',va='center',fontsize=12)
    cnt={'mon':3,'mgr':2,'mds.cephfs':2,'rgw.s3':2,'crash':6}[s]
    for k,h in enumerate(f):
        ax.add_patch(Rectangle((k*1.5,y),1.4,0.8,fc=cols[hosts.index(h)],ec='k',lw=3 if k<cnt else 0.8,alpha=1 if k<cnt else 0.45))
        ax.text(k*1.5+0.7,y+0.4,h,ha='center',va='center',fontsize=12)
    ax.text(9.2,y+0.4,f'count={cnt}' if s!='crash' else 'all hosts (no count)',fontsize=12,va='center')
ax.set_xlim(-2.3,11.5); ax.set_ylim(-0.3,len(svcs)); ax.axis('off')
ax.set_title('HostAssignment.get_candidates: sorted(hosts) shuffled with Random(sha1(service_name) mod 2^32); bold = first picks for a fresh cluster',fontsize=13)
plt.tight_layout(); plt.savefig(D+'f06_place.png'); plt.close()
# f07 db slots
def alloc(nhdd,nnvme,vg):
    slots=-(-nhdd//nnvme); out=[]; left=nhdd
    for d in range(nnvme):
        n=min(slots,left); out.append((d,slots,n,vg/slots)); left-=n
    return out
fig,axs=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
for ax,(nh,nn) in zip(axs,((12,2),(10,3))):
    vg=1490.0
    res=alloc(nh,nn,vg)
    for d,slots,n,sz in res:
        for s in range(slots):
            used=s<n
            ax.add_patch(Rectangle((s*sz,d),sz*0.98,0.7,fc='#5DADE2' if used else '#FDFEFE',ec='k',hatch=None if used else '//'))
            if used: ax.text(s*sz+sz/2,d+0.35,f'db{d*slots+s}\n{sz:.1f} GiB',ha='center',va='center',fontsize=10)
        ax.text(-30,d+0.35,f'nvme{d}',ha='right',va='center',fontsize=12)
    ax.set_xlim(-160,vg+20); ax.set_ylim(-0.3,nn+0.2); ax.set_yticks([]); ax.set_xlabel('VG size (GiB), 1490 GiB per NVMe (example)',fontsize=12)
    ax.set_title(f'{nh} HDD + {nn} NVMe: fast_slots_per_device = ceil({nh}/{nn}) = {-(-nh//nn)}, abs_size = vg_size / slots',fontsize=12)
plt.tight_layout(); plt.savefig(D+'f07_dbslots.png'); plt.close()
# f09 ok-to-stop
H,P=mk(); S,log=maximize(0,H,P,2)
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
ax.add_patch(FancyBboxPatch((6.2,5.2),2.6,0.8,boxstyle='round,pad=0.05',fc='#EEE',ec='k')); ax.text(7.5,5.6,'root default (2nd parent)',ha='center',va='center',fontsize=12)
res={o:st for (_,o,st,_) in log}; bad={o:b for (_,o,st,b) in log}
for h in range(4):
    x=h*3.8+0.3
    ax.add_patch(FancyBboxPatch((x,3.2),3.2,0.8,boxstyle='round,pad=0.05',fc='#FDEBD0' if h==0 else '#EEE',ec='k')); ax.text(x+1.6,3.6,f'host-{chr(97+h)}'+(' (1st parent)' if h==0 else ''),ha='center',va='center',fontsize=12)
    ax.plot([x+1.6,7.5],[4.05,5.15],color='#888')
    for i,o in enumerate(H[h]):
        ox=x+i*1.1; c='#58D68D' if o in S else '#F1948A'
        ax.add_patch(Rectangle((ox,1.4),1.0,0.9,fc=c,ec='k')); ax.text(ox+0.5,1.85,f'osd.{o}',ha='center',va='center',fontsize=11)
        ax.plot([ox+0.5,x+1.6],[2.35,3.15],color='#888')
        lab='start' if o==0 else ('added' if res.get(o)=='add' else f'rejected\n{bad[o]} PGs < min')
        ax.text(ox+0.5,0.95,lab,ha='center',va='top',fontsize=9.5)
ax.set_xlim(0,15.6); ax.set_ylim(0,6.3); ax.axis('off')
ax.set_title('DaemonServer::_maximize_ok_to_stop_set: replicated size 3, min_size 2, 4 hosts x 3 OSDs, 128 PGs (simulated); result {0,1,2}',fontsize=13)
plt.tight_layout(); plt.savefig(D+'f09_oktostop.png'); plt.close()
