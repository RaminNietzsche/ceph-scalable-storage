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
D='figures/ch12/'
K=1024
def ru(x,a): return -(-x//a)*a
def acc(blob,clen,mas,crr=0.875):
    want=ru(int(blob*crr),mas); res=ru(clen,mas); return res<=want and res<blob, want, res
for c in [50*K,57*K+512,30*K]:
    for mas in [4*K,64*K]: print(c,mas,acc(64*K,c,mas))
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
cl=np.arange(1*K,64*K+1,256)
for a,mas,ttl in [(ax[0],4*K,'min_alloc_size 4K (default since Pacific)'),(ax[1],64*K,'min_alloc_size 64K (old HDD OSDs)')]:
    alloc=[ (ru(c,mas) if acc(64*K,c,mas)[0] else 64*K)/K for c in cl]
    a.plot(cl/K,alloc,color='#2471a3',lw=2,label='allocated on disk')
    a.plot(cl/K,cl/K,ls=':',color='gray',label='compressed size')
    w=acc(64*K,0,mas)[1]/K; a.axvline(w,color='#c0392b',ls='--'); a.text(w-1,8,'accept if roundup(len) <= %g K\n(64K x 0.875 rounded up)'%w,ha='right',color='#c0392b')
    a.set_xlabel('compressed length of a 64 KiB blob (KiB)'); a.set_ylabel('KiB allocated'); a.set_title(ttl); a.legend(loc='upper left'); a.set_ylim(0,70)
fig.suptitle('BlueStore compression accept test: p2roundup(compressed, min_alloc) <= p2roundup(blob x required_ratio, min_alloc) and < blob')
fig.tight_layout(); fig.savefig(D+'f08_compress.png',dpi=110)
# f09 min_alloc amplification
sizes=[1,4,10,16,40,100,1000]
fig,ax=plt.subplots(figsize=(16,6.5))
x=np.arange(len(sizes))
for i,(mas,c) in enumerate([(4,'#27ae60'),(16,'#f5b041'),(64,'#c0392b')]):
    amp=[ru(s,mas)/s for s in sizes]
    ax.bar(x+(i-1)*0.27,amp,0.27,color=c,label='min_alloc %dK'%mas)
    for xi,v in zip(x,amp): ax.text(xi+(i-1)*0.27,v+0.3,'%.2g'%v,ha='center',fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(['%d KiB'%s for s in sizes]); ax.set_ylabel('allocated / logical (per replica)')
ax.set_title('space amplification of small objects: allocated = roundup(size, min_alloc_size)  (e.g. 100 M x 10 KiB objects: 1.1 TiB at 4K vs 6.0 TiB at 64K per replica)')
ax.legend(); fig.tight_layout(); fig.savefig(D+'f09_minalloc.png',dpi=110)
# f10 rocksdb levels
lv=['L1','L2','L3','L4']; sz=[1,8,64,512]; cum=np.cumsum(sz)
fig,ax=plt.subplots(figsize=(16,6.5))
ax.bar(lv,sz,color='#5dade2',label='level target size (GiB)')
ax.plot(lv,cum,'o-',color='#c0392b',label='cumulative L1..Ln (GiB)')
for i,(s,c) in enumerate(zip(sz,cum)): ax.text(i,c*1.15,'%d GiB total'%c,ha='center',color='#c0392b'); ax.text(i,s*0.6,'%d'%s,ha='center')
ax.set_yscale('log'); ax.set_ylabel('GiB (log)')
ax.set_title('static RocksDB level targets from bluestore_rocksdb_options: max_bytes_for_level_base 1 GiB, multiplier 8 (plus L0 and WAL ~1 GiB each)')
ax.legend(loc='upper left'); fig.tight_layout(); fig.savefig(D+'f10_levels.png',dpi=110)
