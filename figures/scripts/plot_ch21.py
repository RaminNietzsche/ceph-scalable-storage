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
import matplotlib.pyplot as plt, numpy as np, random, sys
from matplotlib.patches import Rectangle
from dmc import sim
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch21/'
# f07 shards
fig,(a1,a2)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
r=random.Random(5); ps=r.sample(range(4096),100); c=[0]*8
for p in ps: c[p%8]+=1
a1.bar(range(8),c,color='#5DADE2',edgecolor='k'); a1.axhline(12.5,color='k',ls='--'); a1.text(-0.4,13,'mean 12.5',ha='left',fontsize=12)
for i,v in enumerate(c): a1.text(i,v+0.3,str(v),ha='center',fontsize=12)
a1.set_xlabel('OSDShard index = pg.ps() mod 8',fontsize=12); a1.set_ylabel('PGs mapped to shard',fontsize=12)
a1.set_title('one SSD OSD with 100 PGs (random ps from pg_num 4096), osd_op_num_shards_ssd = 8',fontsize=12)
mx=[]
for s in range(2000):
    ps=random.Random(s).sample(range(4096),100); cc=[0]*8
    for p in ps: cc[p%8]+=1
    mx.append(max(cc)/12.5)
a2.hist(mx,bins=30,color='#F5B041',edgecolor='k'); a2.axvline(np.median(mx),color='k',ls='--'); a2.text(np.median(mx)+0.01,a2.get_ylim()[1]*0.9,f'median {np.median(mx):.2f}',fontsize=12)
a2.axvline(np.percentile(mx,95),color='#C0392B',ls=':'); a2.text(np.percentile(mx,95)+0.01,a2.get_ylim()[1]*0.75,f'p95 {np.percentile(mx,95):.2f}',fontsize=12,color='#C0392B')
a2.set_xlabel('busiest shard PG count / mean (2000 random OSDs)',fontsize=12); a2.set_ylabel('OSDs',fontsize=12)
a2.set_title('shard PG imbalance is normal: equal PG load still gives uneven shards',fontsize=12)
plt.tight_layout(); plt.savefig(D+'f07_shards.png'); plt.close()
# f08 autotune
GiB=2**30
items=[('mon (usage 2.1)',2.1),('mgr (min 4.0)',4.0),('crash (min 0.125)',0.125),('node-exporter (default 1.0)',1.0),('rgw (usage 1.5)',1.5)]
fig,ax=plt.subplots(figsize=(16,5.5),dpi=110)
x=0; cols=['#AF7AC5','#5DADE2','#F7DC6F','#A3E4D7','#F0B27A']
ax.add_patch(Rectangle((0,1.2),256,0.6,fc='#EEE',ec='k')); ax.text(128,1.5,'host memory_total = 256 GiB',ha='center',va='center',fontsize=13)
ax.add_patch(Rectangle((179.2,1.2),76.8,0.6,fc='#FFFFFF',ec='k',hatch='//')); ax.text(217.6,1.5,'30% left for OS / page cache',ha='center',va='center',fontsize=12)
for (n,v),cl in zip(items,cols):
    ax.add_patch(Rectangle((x,0.2),v,0.6,fc=cl,ec='k')); x+=v
ax.annotate('non-OSD daemons: 8.725 GiB (mon, mgr, crash, node-exporter, rgw)',(4.3,0.8),xytext=(10,1.0),fontsize=12,arrowprops=dict(arrowstyle='->'))
per=(179.2-8.725)/20
for i in range(20):
    ax.add_patch(Rectangle((x+i*per,0.2),per,0.6,fc='#58D68D',ec='k',lw=0.6))
ax.text(x+10*per,0.5,f'20 OSDs x {per:.3f} GiB = osd_memory_target (set for osd/host:<host>)',ha='center',va='center',fontsize=12)
ax.set_xlim(-2,258); ax.set_ylim(0,2); ax.set_yticks([]); ax.set_xlabel('GiB',fontsize=12)
ax.set_title('cephadm MemoryAutotuner: total = 256 GiB x autotune_memory_target_ratio 0.7 = 179.2 GiB, minus other daemons, split evenly',fontsize=13)
plt.tight_layout(); plt.savefig(D+'f08_autotune.png'); plt.close()
# f09 write split
K=1024
cases=[('16K @ 0 (new object)',0,16*K),('64K @ 0',0,64*K),('70K @ 6K',6*K,70*K),('1K @ 100',100,1*K),('4K @ 8K',8*K,4*K)]
fig,ax=plt.subplots(figsize=(16,7),dpi=110)
mas=4*K
for r,(n,off,ln) in enumerate(cases):
    y=len(cases)-1-r; end=off+ln
    for b in range(0,80*K,mas): ax.add_patch(Rectangle((b/K,y),4,0.6,fc='none',ec='#CCC',lw=0.5))
    if off//mas==(end-1)//mas and ln!=mas:
        segs=[('small',off,ln)]
    else:
        hl=(-off)%mas; tl=end%mas; ml=ln-hl-tl; segs=[]
        if hl: segs.append(('small',off,hl))
        segs.append(('big',off+hl,ml))
        if tl: segs.append(('small',end-tl,tl))
    lab=[]
    for kind,o,l in segs:
        if kind=='small': fc='#F7DC6F'; d='small path'
        else:
            fc='#F1948A' if l<64*K else '#5DADE2'; d=('big, deferred (%dK < 64K)'%(l//K)) if l<64*K else ('big, direct (%dK >= 64K)'%(l//K))
        ax.add_patch(Rectangle((o/K,y),l/K,0.6,fc=fc,ec='k')); lab.append(d)
    ax.text(-1,y+0.3,n,ha='right',va='center',fontsize=12)
    ax.text(81,y+0.3,'; '.join(lab),va='center',fontsize=11)
ax.set_xlim(-22,128); ax.set_ylim(-0.3,len(cases)); ax.set_yticks([]); ax.set_xlabel('object offset (KiB); grey grid = min_alloc_size 4K',fontsize=12)
ax.set_title('BlueStore::_do_write_data (classic path, bluestore_write_v2=false) on HDD: prefer_deferred_size_hdd = 64K',fontsize=13)
plt.tight_layout(); plt.savefig(D+'f09_writesplit.png'); plt.close()
# f10 dmclock
fig,axs=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
cl={'client':(300,1,0),'recovery':(100,1,200),'scrub':(0,2,0)}
for ax,cap in zip(axs,(1000,350)):
    r=sim(cl,cap=cap,secs=4)
    names=list(cl); res=[np.mean(r[n][1][1:]) for n in names]; tot=[np.mean(r[n][0][1:]) for n in names]
    ax.bar(names,res,color='#5DADE2',edgecolor='k',label='served in reservation phase')
    ax.bar(names,np.array(tot)-np.array(res),bottom=res,color='#F5B041',edgecolor='k',label='served in weight phase')
    for i,(a,b) in enumerate(zip(res,tot)): ax.text(i,b+8,f'{b:.0f}/s',ha='center',fontsize=13)
    ax.set_xticks(range(3)); ax.set_xticklabels([f'{n}\nres={cl[n][0]} wgt={cl[n][1]} lim={cl[n][2] or "none"}' for n in names],fontsize=11)
    ax.set_ylim(0,620); ax.set_ylabel('requests per second (cost 1)',fontsize=12); ax.legend(fontsize=11,loc='upper left')
    ax.set_title(f'server capacity {cap} req/s ' + ('(reservations fit)' if cap==1000 else '(overcommitted: 350 < 400 reserved)'),fontsize=13)
plt.tight_layout(); plt.savefig(D+'f10_dmclock.png'); plt.close()
