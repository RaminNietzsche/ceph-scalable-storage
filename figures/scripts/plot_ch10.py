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
D='figures/ch10/'
M=1<<20
# f06 bench guard
bs=np.array([4096,8192,16384,65536,262144,524288,M-1,M,4*M,16*M,64*M],dtype=float)
mx=[b*30*100 if b<M else 100*M*30 for b in bs]
fig,ax=plt.subplots(figsize=(16,6.5))
ax.loglog(bs,np.array(mx)/M,'o-',color='#2E86C1',lw=2,base=2)
ax.axvline(64*M,color='#C0392B',ls='--'); ax.text(64*M*0.9,200,'osd_bench_max_block_size 64M\n(larger bsize -> EINVAL)',color='#C0392B',ha='right',fontsize=11)
ax.axvline(M,color='gray',ls=':'); ax.text(M*1.1,30,'1 MiB: switch from IOPS rule to throughput rule',fontsize=11)
ax.plot([4096],[12288000/M],'*',ms=20,color='#E67E22'); ax.annotate('mClock startup bench: bsize 4K, count 12288000 B\n= 4096 x 30 s x 100 IOPS (exactly the cap), 3000 writes into 100 x 4 MiB objects',(4096,12288000/M),xytext=(4096*2,300),fontsize=11,arrowprops=dict(arrowstyle='->'))
ax.set_xticks([4096,65536,M,16*M,64*M]); ax.set_xticklabels(['4K','64K','1M','16M','64M'])
ax.set_xlabel('bsize'); ax.set_ylabel('max count (MiB)')
ax.set_title('OSD bench guard: count <= bsize x osd_bench_duration(30) x small_size_max_iops(100) below 1M, else <= large_size_max_throughput(100M) x 30',fontsize=12)
ax.grid(alpha=.3,which='both'); fig.tight_layout(); fig.savefig(D+'f06_benchguard.png',dpi=110)
# f07 capacity thresholds
fig,ax=plt.subplots(2,1,figsize=(16,6.5))
for a,(name,lo,hi,dflt,meas) in zip(ax,[('HDD',50,500,315,[(300,'measured 300 -> stored'),(6000,'measured 6000 (write cache) -> rejected, keep 315'),(20,'measured 20 -> rejected')]),('SSD',1000,80000,21500,[(45000,'measured 45000 -> stored'),(250000,'measured 250000 -> rejected, keep 21500')])]):
    a.set_xscale('log'); a.axvspan(lo,hi,color='#D5F5E3'); a.axvline(dflt,color='#2E86C1',lw=2); a.text(dflt*1.05,0.72,f'default {dflt}',color='#2E86C1',fontsize=11)
    a.text(lo*1.05,0.88,f'accepted range [{lo}, {hi}]',fontsize=11,color='#1E8449')
    for k,(v,t) in enumerate(meas):
        c='#27AE60' if lo<=v<=hi else '#C0392B'; a.plot([v],[0.5],'o',ms=12,color=c); a.text(v*1.05,0.5+(0.15 if k%2 else -0.25),t,fontsize=11,color=c)
    a.set_ylim(0,1); a.set_yticks([]); a.set_xlim(8,600000); a.set_title(f'{name}: osd_mclock_max_capacity_iops_{name.lower()} after the startup bench',fontsize=12)
fig.tight_layout(); fig.savefig(D+'f07_mclockcap.png',dpi=110)
# f08 profile allocation (v21.2.0 values), HDD defaults
bw=150*M; iops=315; cost=bw/iops
prof={'balanced':[(.5,1,0),(.5,1,0),(.05,2,.9)],'high_client_ops':[(.6,2,0),(.4,1,0),(.05,4,.7)],'high_recovery_ops':[(.3,1,0),(.7,2,0),(.05,2,0)]}
cls=['client','background_recovery','background_best_effort']
fig,ax=plt.subplots(figsize=(16,6.5)); x=np.arange(3); w=0.26
cols=['#2E86C1','#E67E22','#7F8C8D']
for i,(pn,v) in enumerate(prof.items()):
    for j,(r,wt,l) in enumerate(v):
        res=r*bw/cost; lim=(l if l else 1)*bw/cost
        ax.bar(x[i]+(j-1)*w,lim,w,color=cols[j],alpha=.25,edgecolor=cols[j])
        ax.bar(x[i]+(j-1)*w,res,w,color=cols[j],label=cls[j] if i==0 else None)
        ax.text(x[i]+(j-1)*w,res+4,f'res {res:.0f}\nw {wt}\nlim {"max" if not l else f"{lim:.0f}"}',ha='center',fontsize=10)
ax.set_xticks(x); ax.set_xticklabels(list(prof)); ax.set_ylabel('IOPS-equivalent (4K ops, HDD 315 IOPS / 150 MiB/s)')
ax.legend(loc='upper right'); ax.set_ylim(0,360)
ax.set_title(f'mClock profiles in v21.2.0: reservation (solid) and limit (light) per class; cost per IO = 150 MiB / 315 = {cost:.0f} bytes',fontsize=12)
fig.tight_layout(); fig.savefig(D+'f08_mclockprof.png',dpi=110)
print(cost, 0.5*bw/cost, 0.05*bw/cost, .9*bw/cost, 1200*M/21500)
