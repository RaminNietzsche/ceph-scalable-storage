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
import matplotlib.pyplot as plt, numpy as np, sys
from matplotlib.patches import Rectangle
from ch20 import bucket, rng, prom_rate, predict_linear
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch20/'
# f07 histogram buckets
fig,(a1,a2)=plt.subplots(1,2,figsize=(16,6.8),dpi=110)
rs=np.random.RandomState(7)
lat=np.concatenate([rs.lognormal(np.log(700),0.5,6000),rs.lognormal(np.log(9000),0.6,900)])  # usec, synthetic
size=np.concatenate([np.full(4000,4096),np.full(2000,65536),np.full(900,4*2**20)])
rs.shuffle(size)
H=np.zeros((18,18))
for l,s in zip(lat,size):
    H[min(bucket(int(l*1000),0,100000,32),17), min(bucket(int(s),0,512,32),17)]+=1
im=a1.imshow(np.log10(H+1).T,origin='lower',cmap='viridis',aspect='auto')
a1.set_xlabel('latency bucket i  (range [100us*2^(i-2), 100us*2^(i-1)) )',fontsize=12); a1.set_ylabel('request size bucket j  ([512*2^(j-2), 512*2^(j-1)) bytes)',fontsize=12)
a1.set_xticks(range(0,18,2)); a1.set_yticks(range(0,18,2))
for j,lab in ((5,'4 KiB'),(9,'64 KiB'),(15,'4 MiB')): a1.text(17.3,j,lab,color='w',fontsize=11,ha='right',va='center')
a1.set_title('op_w_latency_in_bytes_histogram (synthetic load, log10 count)',fontsize=13); plt.colorbar(im,ax=a1)
xs=list(range(1,20)); lo=[rng(i,0,100000)[0]/1000 for i in xs]; hi=[(rng(i,0,100000)[1]+1)/1000 for i in xs]
a2.bar(xs,np.array(hi)-np.array(lo),bottom=np.maximum(lo,1),color='#5DADE2',edgecolor='k'); a2.set_yscale('log')
for v,c in ((150,'#C0392B'),(1500,'#C0392B'),(30000,'#C0392B')):
    b=bucket(v*1000,0,100000,32); a2.plot([b],[v],'o',color=c,ms=9); a2.annotate(f'{v} us -> bucket {b}',(b,v),xytext=(b+1.2,v/3),fontsize=12,arrowprops=dict(arrowstyle='->'))
a2.set_xlabel('latency bucket i',fontsize=12); a2.set_ylabel('bucket range (us), log scale',fontsize=12)
a2.set_title('SCALE_LOG2, min 0, quant 100000 ns, 32 buckets (bucket 31: >= 53687 s)',fontsize=13); a2.grid(alpha=.3,which='both')
plt.tight_layout(); plt.savefig(D+'f07_hist.png'); plt.close()
# f08 stale cache
dur=[5,5,6,17,18,6,5,5]; t=0; col=[]
for d in dur:
    col.append((t,t+d,d)); t=t+d+max(0,15-d)
fig,ax=plt.subplots(figsize=(16,6),dpi=110)
for s,e,d in col:
    ax.add_patch(Rectangle((s,2),e-s,0.6,fc='#F5B041' if d>=15 else '#58D68D',ec='k')); ax.text((s+e)/2,2.3,f'{d}s',ha='center',va='center',fontsize=13)
def state(ts):
    last=None
    for s,e,d in col:
        if e<=ts: last=d
    return last
for k,strat,y in ((0,'fail (also used for the default value "log")',1),(1,'return',0)):
    for st in np.arange(10,t,15):
        L=state(st)
        if L is None: c='#BBBBBB'; lab='503 empty'
        elif L<15: c='#58D68D'; lab='200'
        else: c='#E74C3C' if strat.startswith('fail') else '#F5B041'; lab='503' if strat.startswith('fail') else '200 stale'
        ax.add_patch(Rectangle((st-2.5,y),5,0.75,fc=c,ec='k')); ax.text(st,y+0.37,lab,ha='center',va='center',fontsize=11,rotation=90)
    ax.text(-3,y+0.3,f'scrape every 15 s,\nstrategy={strat.split(" ")[0]}',ha='right',va='center',fontsize=11)
ax.text(-3,2.3,'MetricCollectionThread\ncollect() duration',ha='right',va='center',fontsize=11)
ax.set_xlim(-30,t+5); ax.set_ylim(-0.3,3); ax.set_yticks([]); ax.set_xlabel('time (s)',fontsize=12)
ax.set_title('mgr/prometheus cache: stale = last collect() took >= scrape_interval (15 s); default "log" is not a valid value and falls back to fail',fontsize=12)
plt.tight_layout(); plt.savefig(D+'f08_cache.png'); plt.close()
# f09 flapping
ts=np.arange(0,600,15); up=np.ones(len(ts))
for k in (22,25,28,31,34,37,39): up[k]=0
fig,(a1,a2)=plt.subplots(2,1,figsize=(16,7),dpi=110,sharex=True)
a1.step(ts,up,where='post',color='#4A72C4',lw=2); a1.plot(ts,up,'k.',ms=6); a1.set_ylabel('ceph_osd_up',fontsize=12); a1.set_ylim(-0.2,1.3)
a1.axvspan(285,585,color='#F9E79F',alpha=.5); a1.text(435,1.12,'[5m] window at t=585 s: 7 down/up cycles seen in samples',ha='center',fontsize=12)
ev=[(te,prom_rate(list(ts),list(up),te,300)) for te in ts if te>=30]
a2.plot([e[0] for e in ev],[ (e[1] or 0)*60 for e in ev],'o-',color='#C0392B'); a2.axhline(1,ls='--',color='k'); a2.text(5,1.05,'threshold: > 1 per minute',fontsize=11)
a2.set_ylabel('rate(ceph_osd_up[5m]) * 60',fontsize=12); a2.set_xlabel('evaluation time (s), scrape interval 15 s',fontsize=12)
a1.set_title('CephOSDFlapping: rate() treats every 0->1 step as a counter increase (1->0 is a "reset"); no for: clause',fontsize=13)
plt.tight_layout(); plt.savefig(D+'f09_flap.png'); plt.close()
# f10 imbalance
pg=[92,95,98,100,101,103,104,106,110,141]; a=np.mean(pg)
fig,ax=plt.subplots(figsize=(16,6),dpi=110)
c=['#E74C3C' if abs(p-a)/a>0.3 else '#5DADE2' for p in pg]
ax.axhspan(a*0.7,a*1.3,color='#D5F5E3',alpha=.6,zorder=0); ax.bar(range(10),pg,color=c,edgecolor='k',zorder=2); ax.axhline(a,color='k',zorder=3)
for i,p in enumerate(pg): ax.text(i,p+2,f'{(p-a)/a*100:+.1f}%',ha='center',fontsize=12)
ax.text(-1.75,a*1.3+2,'avg x 1.3 = 136.5',ha='left',fontsize=12); ax.text(-1.75,a*0.7+2,'avg x 0.7 = 73.5',ha='left',fontsize=12,zorder=4); ax.text(-1.75,a+2,'avg = 105',ha='left',fontsize=12,zorder=4)
ax.set_xticks(range(10)); ax.set_xticklabels([f'osd.{i}' for i in range(10)],fontsize=12); ax.set_ylabel('ceph_osd_numpg (device class hdd)',fontsize=12)
ax.set_title(f'CephPGImbalance: |numpg - avg| / avg > 0.30 for 5m, avg per (cluster, job, device_class) = {a:.0f}',fontsize=13); ax.set_ylim(0,165); ax.set_xlim(-1.8,9.6)
plt.tight_layout(); plt.savefig(D+'f10_imbalance.png'); plt.close()
# f11 growth
rs=np.random.RandomState(3)
t=np.arange(0,48*3600+1,600); v=0.70+0.08*t/(48*3600)+rs.normal(0,0.004,len(t))
p=predict_linear(list(t),list(v),t[-1],5*86400)
fig,ax=plt.subplots(figsize=(16,6),dpi=110)
ax.plot(t/3600,v,'.',color='#4A72C4',label='ceph_pool_percent_used samples (synthetic, 10 min step)')
b,a0=np.polyfit(t-t[-1],v,1); tt=np.array([0,48*3600+5*86400])
ax.plot(tt/3600,a0+b*(tt-t[-1]),'--',color='#C0392B',label=f'least-squares fit over [2d], slope {b*86400:.3f}/day')
ax.plot([(48*3600+5*86400)/3600],[p],'o',color='#C0392B',ms=10); ax.annotate(f'predict_linear(..., 5d) = {p:.3f} >= 0.95 -> fire',( (48*3600+5*86400)/3600,p),xytext=(70,0.90),fontsize=12,arrowprops=dict(arrowstyle='->'))
ax.axhline(0.95,color='k',ls=':'); ax.axvline(48,color='#777',ls=':'); ax.text(48.5,0.71,'now',fontsize=12)
ax.set_xlabel('hours',fontsize=12); ax.set_ylabel('fraction used',fontsize=12); ax.legend(fontsize=12,loc='upper left'); ax.grid(alpha=.3)
ax.set_title('CephPoolGrowthWarning: predict_linear(ceph_pool_percent_used[2d], 3600*24*5) >= 0.95',fontsize=13)
plt.tight_layout(); plt.savefig(D+'f11_growth.png'); plt.close()
print('pred',p)
