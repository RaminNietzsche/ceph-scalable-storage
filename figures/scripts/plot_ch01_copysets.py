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
import json,matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
plt.rcParams['font.family']='DejaVu Sans'
d={int(k):v for k,v in json.load(open('figures/data/copyset_real.json')).items()}
r={int(k):v for k,v in json.load(open('figures/data/rebuild_real.json')).items()}
pg=sorted(d)
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
a.plot(pg,[d[p]['p_loss']*100 for p in pg],'o-',color='#c0392b',label='P(>=1 PG lost | 3 random OSDs fail)')
a.plot(pg,[100*p/280840 for p in pg],'--',color='#7f8c8d',label='upper bound pg_num / C(120,3)')
for p in pg: a.annotate(f"{d[p]['p_loss']*100:.2f}%",(p,d[p]['p_loss']*100),textcoords='offset points',xytext=(-10,8),fontsize=8)
a.axvline(8192,ls=':',color='#2e86c1');a.text(8192*1.08,1,'~200 PG/OSD\n(8192)',color='#2e86c1',fontsize=9)
a.set_xscale('log',base=2);a.set_yscale('log');a.set_xlabel('pg_num (size=3, host failure domain)');a.set_ylabel('%');a.legend(loc='upper left',fontsize=9)
a.set_title('Exact count of distinct OSD triples from CRUSH (osdmaptool)')
b.plot(pg,[d[p]['fan_avg'] for p in pg],'s-',color='#27ae60',label='avg peer OSDs sharing a PG with one OSD')
b.fill_between(pg,[d[p]['fan_min'] for p in pg],[d[p]['fan_max'] for p in pg],color='#27ae60',alpha=.15,label='min..max over 120 OSDs')
b.axhline(108,ls='--',color='#7f8c8d');b.text(300,110,'max possible = 120 - 12 (same host)',fontsize=9,color='#555')
b2=b.twinx();ks=sorted(r);b2.plot(ks,[r[k]['max_pgs_one_target'] for k in ks],'^-',color='#8e44ad',label='busiest recovery target (PGs) after osd.0 out')
b2.set_ylabel('PGs landing on busiest target',color='#8e44ad')
b.set_xscale('log',base=2);b.set_xlabel('pg_num');b.set_ylabel('OSDs');b.set_ylim(0,125);b.legend(loc='lower right',fontsize=9);b2.legend(loc='center right',fontsize=9)
b.set_title('Recovery fan-out from the same CRUSH maps')
fig.suptitle('120 OSDs = 10 hosts x 12, straw2, chooseleaf host; crushtool --build + osdmaptool --test-map-pgs-dump, Ceph 18.2.7',fontsize=10)
plt.tight_layout();plt.savefig('figures/ch01/f08_copyset.png')
# rebuild
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110);rate=0.15;cap=16
names=['RAID\n1 hot spare']+[f'Ceph pg_num {k}\n{r[k]["pgs_on_osd0"]} PGs, busiest\ntarget {r[k]["max_pgs_one_target"]} PG' for k in ks]
t=[cap/rate]+[r[k]['max_pgs_one_target']*cap/r[k]['pgs_on_osd0']/rate for k in ks]
bars=ax.bar(range(len(t)),t,color=['#c0392b']+['#27ae60']*len(ks))
for i,v in enumerate(t): ax.text(i,v*1.08,f'{v:.1f} h',ha='center')
ax.set_yscale('log');ax.set_xticks(range(len(t)));ax.set_xticklabels(names,fontsize=9);ax.set_ylabel('hours (log)')
ax.set_title('Time to restore redundancy after one full 16 TB disk fails: t = busiest-target PGs x (16 TB / PGs on disk) / rate;  rate = 0.15 TB/h per disk is an ASSUMPTION')
plt.tight_layout();plt.savefig('figures/ch01/f09_rebuild.png')
print([round(x,1) for x in t])
