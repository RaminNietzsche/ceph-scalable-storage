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
r=json.load(open('figures/data/hostfail.json'));P=8192
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
ks=['1','2','3'];x=np.arange(3);w=.27
for i,(key,c,lab) in enumerate([('degraded','#f39c12','degraded (>=1 replica on failed hosts)'),('inactive','#c0392b','inactive: < min_size=2 left, I/O blocks'),('lost','#000000','all 3 replicas on failed hosts')]):
    m=[100*r[k][key]['mean']/P for k in ks];lo=[100*(r[k][key]['mean']-r[k][key]['min'])/P for k in ks];hi=[100*(r[k][key]['max']-r[k][key]['mean'])/P for k in ks]
    a.bar(x+(i-1)*w,m,w,yerr=[lo,hi],capsize=4,color=c,label=lab)
    for xi,v in zip(x+(i-1)*w,m): a.text(xi,v+2,f'{v:.2f}%',ha='center',fontsize=9)
a.set_xticks(x);a.set_xticklabels(['1 host down','2 hosts down','3 hosts down']);a.set_ylabel('% of 8192 PGs');a.set_ylim(0,85)
a.set_title('Exact over all C(10,k) host combinations (bars = mean, whiskers = min..max)');a.legend(loc='upper left',fontsize=9)
N=np.logspace(0,5,200);p=r['2']['inactive']['mean']/P
b.semilogx(N,100*(1-(1-p)**N),color='#c0392b')
for n,lab in [(256,'1 GiB RBD\n(256 x 4 MiB)'),(25600,'100 GiB RBD')]:
    v=100*(1-(1-p)**n);b.plot(n,v,'o',color='k');b.annotate(f'{lab}: {v:.4f}%' if v<99.99 else f'{lab}: ~100%',(n,v),xytext=(n/30,v-25),arrowprops=dict(arrowstyle='->'))
b.plot(10,100*(1-(1-p)**10),'o',color='k');b.annotate(f'10 objects: {100*(1-(1-p)**10):.1f}%',(10,100*(1-(1-p)**10)),xytext=(2,70),arrowprops=dict(arrowstyle='->'))
b.set_xlabel('objects touched by a client (log)');b.set_ylabel('% chance it hits an inactive PG');b.set_ylim(0,105)
b.set_title(f'2 hosts down: {100*p:.2f}% PGs inactive -> who stalls?')
fig.suptitle('Failure-domain loss on 10 hosts x 12 OSDs, size 3 / min_size 2, pg_num 8192 (osdmaptool mapping, before any OSD is marked out)')
plt.tight_layout();plt.savefig('figures/ch17/f09_hostfail.png')
print(p, 1-(1-p)**256)
