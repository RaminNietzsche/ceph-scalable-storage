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
import sys; from rgw import h
import collections,random,string
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch05/'
def occ(names,ns=11,n=128):
    c=collections.Counter()
    for b in names:
        H=h(b)
        for s in range(ns): c[(H+s)%n]+=1
    return [c.get(i,0) for i in range(n)]
num=['bucket-%04d'%i for i in range(1000)]
random.seed(7)
rnd=[''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(12)) for _ in range(1000)]
fig,ax=plt.subplots(2,1,figsize=(16,6.5),sharex=True)
a=occ(num); b=occ(rnd)
ax[0].bar(range(128),a,color='#c0392b'); ax[0].set_title('1000 buckets named bucket-0000..bucket-0999, 11 index shards each  ->  %d of 128 datalog shards used (bases 8,24,...,120)'%sum(1 for x in a if x))
ax[1].bar(range(128),b,color='#2471a3'); ax[1].set_title('1000 random 12-char bucket names, 11 index shards each  ->  128 of 128 used, %d..%d per shard'%(min(b),max(b)))
for x in ax: x.axhline(11000/128,ls='--',color='k',lw=1); x.set_ylabel('bucket shards')
ax[1].set_xlabel('datalog shard = (ceph_str_hash_linux(bucket) + index_shard) % 128')
fig.tight_layout(); fig.savefig(D+'f06_dlshard.png',dpi=110)

fig,ax=plt.subplots(2,1,figsize=(16,6.5),sharex=True)
ax[0].fill_between([0,120],0,1,color='#d6eaf8'); ax[0].text(60,0.5,'12000 PUTs on one bucket shard (every 10 ms, 0-120 s)',ha='center',va='center')
for t in [0,22,44,66,88,110]:
    ax[0].axvline(t,color='#c0392b',lw=3)
    ax[0].text(t+0.6,1.08,'entry @%ds'%t,color='#c0392b',fontsize=9)
ax[0].set_ylim(0,1.3); ax[0].set_yticks([]); ax[0].set_title('busy shard: 6 datalog entries instead of 12000 (first write + renew every 30*3/4 = 22 s)')
for t in [0,5,40,41,100]: ax[1].plot([t,t],[0,0.6],color='#2471a3',lw=2)
for t,l in [(0,'write -> entry'),(22,'renew (write @5 was inside window)'),(44,'renew (write @40)'),(100,'write -> entry (window expired)')]:
    ax[1].axvline(t,color='#c0392b',lw=3,ymin=0.55); ax[1].text(t+0.6,1.1,l,color='#c0392b',fontsize=9)
ax[1].text(60,0.3,'no write between 44 and 100 -> nothing pending -> no renew at 66, 88',ha='center')
ax[1].set_ylim(0,1.3); ax[1].set_yticks([]); ax[1].set_title('sparse writes at 0, 5, 40, 41, 100 s  ->  entries at 0, 22, 44, 100 s')
ax[1].set_xlabel('time (s); rgw_data_log_window = 30, renew timer = 22 s'); ax[1].set_xlim(-2,135)
fig.tight_layout(); fig.savefig(D+'f07_window.png',dpi=110)

fig,ax=plt.subplots(1,2,figsize=(16,6.5))
c=collections.Counter(h('bucket:bucket-%04d'%i)%64 for i in range(1000))
ax[0].bar(range(64),[c.get(i,0) for i in range(64)],color='#c0392b'); ax[0].set_title('mdlog shard of "bucket:bucket-NNNN" (1000 keys)\nonly shards %s used'%sorted(c))
c2=collections.Counter(h('bucket:'+n)%64 for n in rnd)
ax[1].bar(range(64),[c2.get(i,0) for i in range(64)],color='#2471a3'); ax[1].set_title('mdlog shard of 1000 random bucket names\n64 of 64 used, %d..%d per shard'%(min(c2.values()),max(c2.values())))
for x in ax: x.set_xlabel('mdlog shard = ceph_str_hash_linux("section:key") % 64'); x.set_ylabel('keys')
fig.tight_layout(); fig.savefig(D+'f08_mdlog.png',dpi=110)
