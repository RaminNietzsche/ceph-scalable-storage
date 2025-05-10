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
import matplotlib.pyplot as plt, numpy as np, math
plt.rcParams['font.family']='DejaVu Sans'
exec(open('figures/scripts/compute_bloom_false_positive.py').read().split('# skiplist sim')[0])
# skiplist drawing
keys=[3,7,12,19,21,25,31,38,44,50]; hts=[1,3,1,2,1,4,1,2,1,1]
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
xs={k:i+1 for i,k in enumerate(keys)}
ax.add_patch(plt.Rectangle((-0.35,-0.3),0.7,4.6,fc='#E8F0FE',ec='#4A72C4')); ax.text(0,-0.6,'head',ha='center',fontsize=13)
for k,h in zip(keys,hts):
    x=xs[k]; ax.add_patch(plt.Rectangle((x-0.3,-0.3),0.6,h*1.0+0.3,fc='#FFF4D6',ec='#C99A06'))
    ax.text(x,-0.6,str(k),ha='center',fontsize=14,weight='bold')
for lvl in range(4):
    prev=0
    for k,h in zip(keys,hts):
        if h>lvl:
            ax.annotate('',xy=(xs[k]-0.32,lvl+0.2),xytext=(prev+0.32 if prev else 0.35,lvl+0.2),arrowprops=dict(arrowstyle='->',color='#888',lw=1.2))
            prev=xs[k]
    ax.text(11.3,lvl+0.2,f'level {lvl}  (p = 1/4^{lvl})',fontsize=12,va='center')
path=[(0,3),(6,3),(6,2),(6,1),(8,1),(8,0)]
for (x1,y1),(x2,y2) in zip(path,path[1:]):
    ax.annotate('',xy=(x2,y2+0.35),xytext=(x1,y1+0.35),arrowprops=dict(arrowstyle='->',color='#C0392B',lw=2.5))
ax.text(4.2,4.0,'Seek(38): head L3 -> 25 ; L3 next=NULL, drop ; L2 next=NULL, drop ; L1 -> 38 found (prev array kept for insert)',fontsize=12,color='#C0392B',ha='center')
ax.set_xlim(-0.8,13.8); ax.set_ylim(-1,4.5); ax.axis('off')
ax.set_title('InlineSkipList: max_height=12, branching=4. Node = [next ptrs for levels h-1..0][key+value bytes] in one arena allocation',fontsize=14)
plt.tight_layout(); plt.savefig('f05_skiplist.png'); plt.close()
# bloom
b=np.linspace(4,30,200)
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
ax.semilogy(b,[std(x,max(1,int(x*0.69))) for x in b],label='standard Bloom, k=floor(0.69 b) (LegacyBloomImpl::ChooseNumProbes)',lw=2)
ax.semilogy(b,[cl(x,probes(int(x*1000))) for x in b],label='cache-local 512-bit line, k from FastLocalBloomImpl::ChooseNumProbes',lw=2)
for x,c in ((10,'#555'),(20,'#C0392B')):
    y=cl(x,probes(x*1000)); ax.plot([x],[y],'o',color=c,ms=9); ax.annotate(f'{x} bits/key: k={probes(x*1000)}, FP~{y*100:.3f}%',(x,y),xytext=(x+0.6,y*2.5),fontsize=13,color=c)
ax.set_xlabel('bits per key',fontsize=14); ax.set_ylabel('false positive rate',fontsize=14); ax.grid(True,which='both',alpha=.3); ax.legend(fontsize=13)
ax.set_title('Bloom filter FP rate: Ceph sets rocksdb_bloom_bits_per_key=20 (RocksDB 9.11, format_version 6 -> FastLocalBloom)',fontsize=14)
plt.tight_layout(); plt.savefig('f06_bloom.png'); plt.close()
# WAL fragmentation
fig,ax=plt.subplots(figsize=(16,5.2),dpi=110)
B=32768
segs=[(0,0,30000,'#F1F1F1','earlier records'),(0,30000,7,'#C0392B','hdr'),(0,30007,2761,'#9EC5FE','FIRST 2761'),
(1,0,7,'#C0392B','hdr'),(1,7,32761,'#B8E0C2','MIDDLE 32761'),(2,0,7,'#C0392B','hdr'),(2,7,32761,'#B8E0C2','MIDDLE 32761'),
(3,0,7,'#C0392B','hdr'),(3,7,1717,'#FFE08A','LAST 1717'),(3,1724,B-1724,'#FFFFFF','next record starts @1724')]
for blk,off,ln,c,l in segs:
    ax.barh(3-blk,ln,left=off,color=c,edgecolor='k',height=0.6)
    if ln>1500: ax.text(off+ln/2,3-blk,l,ha='center',va='center',fontsize=13)
ax.set_yticks(range(4)); ax.set_yticklabels([f'block {3-i}  [{(3-i)*32}K..{(4-i)*32}K)' for i in range(4)],fontsize=12)
ax.set_xlim(0,B); ax.set_xlabel('offset inside 32 KiB block (kBlockSize = 32768)',fontsize=13)
ax.set_title('log::Writer::AddRecord: 70000-byte WriteBatch starting at block_offset 30000. Header = crc32c(4) + length(2) + type(1) = 7 B',fontsize=14)
plt.tight_layout(); plt.savefig('f08_walfrag.png'); plt.close()
# dynamic levels
G=1<<30
actual=[0,0,0,0.31,3.0,24.0,200.0]
target=[None,None,None,1.0,3.125,25.0,200.0]
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
lv=np.arange(1,7); w=0.38
ax.bar(lv-w/2,[actual[i] for i in lv],w,label='actual size (GiB)',color='#9EC5FE',edgecolor='k')
ax.bar(lv+w/2,[target[i] or 0 for i in lv],w,label='level_max_bytes_ target (GiB)',color='#FFE08A',edgecolor='k')
ax.set_yscale('symlog',linthresh=1); ax.set_xticks(lv); ax.set_xticklabels([f'L{i}'+(' (empty, below base)' if i<3 else (' = base_level' if i==3 else '')) for i in lv],fontsize=12)
for i in lv:
    if target[i] and i<6: ax.text(i,max(actual[i],target[i])*1.25+0.05,f'score={actual[i]/target[i]:.2f}',ha='center',fontsize=13)
ax.legend(fontsize=13); ax.set_ylabel('GiB (symlog)',fontsize=13)
ax.set_title('level_compaction_dynamic_level_bytes=true, base=1 GiB, multiplier=8: targets derived top-down from the last level (200 GiB)',fontsize=14)
plt.tight_layout(); plt.savefig('f09_dynlevels.png'); plt.close()
