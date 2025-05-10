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
import json,re,datetime as dt,statistics as st,matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt,numpy as np
plt.rcParams['font.family']='DejaVu Sans'
def T(s): return dt.datetime.fromisoformat(s.replace('+0330','+03:30')).timestamp()
prim=[];rep=[]
for i in range(3):
    for o in json.load(open(f'figures/data/hist_osd{i}.json'))['ops']:
        d=o['description']
        if ':::o' not in d or not re.search(r' 4\.[0-9a-f]+ ',d): continue
        ev=[(e['event'],T(e['time'])) for e in o['type_data']['events']]
        (prim if d.startswith('osd_op(') else rep if d.startswith('osd_repop(') else []).append(ev)
def stages(ops):
    S={}
    for ev in ops:
        for (a,ta),(b,tb) in zip(ev,ev[1:]):
            b2=re.sub(r'waiting for subops from \d+','waiting for subops',b);a2=re.sub(r'waiting for subops from \d+','waiting for subops',a)
            S.setdefault(f'{a2} -> {b2}',[]).append((tb-ta)*1e6)
    return S
P=stages(prim);R=stages(rep)
print(len(prim),len(rep))
tot=[(ev[-1][1]-ev[0][1])*1e6 for ev in prim];print('primary total median us',st.median(tot))
for k,v in P.items(): print('P',k,len(v),round(st.median(v),1))
for k,v in R.items(): print('R',k,len(v),round(st.median(v),1))
json.dump(dict(P={k:v for k,v in P.items()},R={k:v for k,v in R.items()},tot=tot),open('figures/data/ch22_stages.json','w'))
fig,axs=plt.subplots(1,2,figsize=(16,6.5),dpi=110,gridspec_kw=dict(width_ratios=[1.2,1]))
for ax,S,title,n in [(axs[0],P,'primary: osd_op (client write 4 KiB)',len(prim)),(axs[1],R,'replica: osd_repop',len(rep))]:
    ks=[k for k in S if len(S[k])>=0.8*n]
    med=[st.median(S[k]) for k in ks];p90=[np.percentile(S[k],90) for k in ks]
    y=np.arange(len(ks))
    ax.barh(y,p90,color='#d6eaf8',label='p90');ax.barh(y,med,color='#2e86c1',label='median')
    for yi,m,p in zip(y,med,p90): ax.text(max(p,m)*1.05+0.5,yi,f'{m:.0f} / {p:.0f} us',va='center',fontsize=8)
    ax.set_yticks(y);ax.set_yticklabels(ks,fontsize=8);ax.invert_yaxis();ax.set_xscale('symlog',linthresh=10);ax.set_xlabel('microseconds (symlog)')
    ax.set_title(f'{title}, n={n}');ax.legend(loc='lower right')
fig.suptitle('OpTracker events from dump_historic_ops, pool size 2, 3 BlueStore OSDs, Ceph 18.2.7 test cluster (median / p90 per transition)')
plt.tight_layout();plt.savefig('figures/ch22/f09_optracker.png')
# gantt
ordP=['initiated','header_read','throttled','all_read','dispatched','queued_for_pg','reached_pg','started','waiting for subops','op_commit','sub_op_commit_rec','commit_sent','done']
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
def cum(ops,names):
    rows=[]
    for ev in ops:
        d={re.sub(r'waiting for subops from \d+','waiting for subops',a):t for a,t in ev};t0=d['initiated']
        rows.append([ (d[n]-t0)*1e6 if n in d else np.nan for n in names])
    return np.nanmedian(np.array(rows),axis=0)
cp=cum(prim,ordP)
cols=plt.cm.tab20(np.linspace(0,1,len(ordP)))
for i in range(len(ordP)-1):
    ax.barh(1,cp[i+1]-cp[i],left=cp[i],color=cols[i],edgecolor='k')
    if cp[i+1]-cp[i]>40: ax.text((cp[i]+cp[i+1])/2,1,ordP[i+1].replace('waiting for subops','wait subops'),ha='center',va='center',fontsize=8,rotation=90)
ordR=['initiated','throttled','all_read','dispatched','queued_for_pg','reached_pg','started','commit_sent','done']
cr=cum(rep,ordR);off=cp[ordP.index('waiting for subops')]
# replica op starts after primary sends; approx offset = primary 'waiting for subops' median (network on loopback ~ tens of us)
for i in range(len(ordR)-1):
    ax.barh(0,cr[i+1]-cr[i],left=off+cr[i],color=cols[i],edgecolor='k',hatch='//')
ax.text(off+cr[-2]/2,0,'replica: started -> commit_sent\n(BlueStore txc + kv sync)',ha='center',va='center',fontsize=9)
ax.set_yticks([0,1]);ax.set_yticklabels(['replica osd_repop\n(shifted to primary send time)','primary osd_op'])
n1=sum(1 for ev in prim if [a for a,_ in ev].index('op_commit')<[a for a,_ in ev].index('sub_op_commit_rec')) if True else 0
ax.set_xlabel('microseconds since initiated (median of 300 writes)')
ax.set_title(f'Median timeline of a 4 KiB replicated write; local op_commit came before replica ack in {n1}/300 ops')
plt.tight_layout();plt.savefig('figures/ch22/f10_opgantt.png');print(n1,cp.round(0),cr.round(0))
