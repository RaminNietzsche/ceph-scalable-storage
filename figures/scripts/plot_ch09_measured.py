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
L=json.load(open('figures/data/mgr09_lag.json'));P=sorted(L,key=int)
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
for p in P:
    x=sorted(L[p]);a.step(x,np.arange(1,len(x)+1)/len(x),where='post',lw=2,label=f'mgr_stats_period = {p} s')
a.set_xlabel('seconds from write_full() until pg dump shows the new object');a.set_ylabel('fraction of 15 trials');a.legend();a.set_title('CDF of stats staleness')
pos=np.arange(len(P));a2=b
b.boxplot([L[p] for p in P],positions=pos,widths=.5)
b.plot(pos,[int(p) for p in P],'r--',label='y = period');b.plot(pos,[2*int(p) for p in P],'r:',label='y = 2 x period')
b.set_xticks(pos);b.set_xticklabels([f'{p} s' for p in P]);b.set_xlabel('mgr_stats_period');b.set_ylabel('lag (s)');b.legend();b.set_title('Lag vs period (measured)')
fig.suptitle('How stale is what Dashboard/CLI sees? Measured on a 3-OSD test cluster, Ceph 18.2.7 (default mgr_stats_period = 5)')
plt.tight_layout();plt.savefig('figures/ch09/f09_statslag.png')
D=json.load(open('figures/data/mgr09_dump.json'));n=[d['pgs'] for d in D]
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
for k,c in [('pg dump','#c0392b'),('pg dump pgs_brief','#2e86c1'),('status','#27ae60')]:
    a.loglog(n,[d[k]['bytes'] for d in D],'o-',color=c,label=k);b.loglog(n,[d[k]['ms'] for d in D],'o-',color=c,label=k)
for x,d in zip(n,D): a.annotate(f"{d['pg dump']['bytes']/x/1024:.1f} KiB/PG",(x,d['pg dump']['bytes']),xytext=(4,6),textcoords='offset points',fontsize=8)
a.set_xlabel('PGs in cluster');a.set_ylabel('JSON reply bytes');a.legend();a.set_title('Reply size')
b.set_xlabel('PGs in cluster');b.set_ylabel('median ms (10 calls, local client)');b.legend();b.set_title('Call latency')
fig.suptitle('Cost of polling the mgr: full pg dump grows ~2.4 KiB per PG; status stays constant (measured, Ceph 18.2.7)')
plt.tight_layout();plt.savefig('figures/ch09/f10_dumpcost.png')
