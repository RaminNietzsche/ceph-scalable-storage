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
import sys,math,random
from ch01 import model
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch01/'
pgs=[64,128,256,512,1024,2048,4096,8192,16384,32768,65536]
P=[];L=[]
C=math.comb(120,3)
for g in pgs:
    n,T,p=model(pgs=g); P.append(n/C); L.append(n/C/g)
    if g in (4096,8192): print(g,n,round(n/C,4))
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
ax[0].plot(pgs,[p*100 for p in P],'o-',color='#c0392b'); ax[0].set_xscale('log',base=2)
ax[0].axvline(8192,ls='--',color='gray'); ax[0].text(8192*1.1,2,'200 PG/OSD x 120 / 3 = 8000 -> 8192',fontsize=9)
for g,p in zip(pgs,P):
    if g in (1024,8192,65536): ax[0].text(g,p*100+1,'%.2f%%'%(p*100),ha='center')
ax[0].set_xlabel('pg_num (size 3, 10 hosts x 12 OSDs)'); ax[0].set_ylabel('P(3 random simultaneous OSD failures lose a PG) %')
ax[0].set_title('more PGs -> more distinct OSD triples -> higher chance some PG loses all copies')
ax[1].plot(pgs,[l*100 for l in L],'o-',color='#2471a3'); ax[1].set_xscale('log',base=2)
ax[1].set_ylim(0,max(L)*100*1.3); ax[1].set_xlabel('pg_num'); ax[1].set_ylabel('expected fraction of pool lost per such event (%)')
ax[1].set_title('...but each lost PG holds 1/pg_num of the data: expected loss ~ flat')
fig.suptitle('copyset trade-off with random host-level placement (model, Monte Carlo; failure domain host => same-host triples never lose data)')
fig.tight_layout(); fig.savefig(D+'f08_copyset.png',dpi=110)
# f09 RAID vs declustered rebuild model
fig,ax=plt.subplots(figsize=(16,6.5))
disk_tb=16; rate=0.15 # TB/h per disk write (≈ 42 MB/s effective under load)
import numpy as np
n=np.array([4,8,12,24,48,96,120])
raid=[disk_tb/rate]*len(n)
ceph=[disk_tb/((k-1)*rate) for k in n]
ax.plot(n,raid,'s-',color='#c0392b',label='RAID: one spare disk writes everything (16 TB / 0.15 TB/h)')
ax.plot(n,ceph,'o-',color='#27ae60',label='declustered (Ceph): N-1 surviving OSDs each rebuild 1/(N-1)')
for x,y in zip(n,ceph): ax.text(x,y*1.15,'%.1f h'%y,ha='center',fontsize=9)
ax.text(60,raid[0]*1.08,'%.0f h'%raid[0],color='#c0392b')
ax.set_yscale('log'); ax.set_xlabel('OSDs (disks) sharing the failed disk\'s data'); ax.set_ylabel('hours to restore redundancy (log)')
ax.set_title('rebuild-time model (illustrative rates; real Ceph recovery is limited by mClock profile, network and osd_max_backfills)')
ax.legend(); fig.tight_layout(); fig.savefig(D+'f09_rebuild.png',dpi=110)
