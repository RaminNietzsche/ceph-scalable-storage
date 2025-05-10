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
D='figures/ch24/'
# ---- fragmentation score reimplementation
BS=4096
scales=[1.0]
def get_score(v):
    sc=v.bit_length()-1
    while len(scales)<=sc+1:
        ss=len(scales); s=1.2
        if ss>=27: s=1.0
        elif ss>20: s=(1.0*(ss-20)+1.2*(27-ss))/7
        scales.append(scales[-1]*s)
    b=1<<sc; x=(v-b)/b
    return b*scales[sc]*(1-x)+2*b*scales[sc+1]*x
def frag(chunks):
    tot=sum(chunks); act=sum(get_score(c) for c in chunks)
    ideal=get_score(tot); terr=(tot//BS)*get_score(BS)
    return (ideal-act)/(ideal-terr)
G=1<<30
res={}
for cs in [4096,16384,65536,1<<20,16<<20,128<<20,256<<20,G]:
    n=G//cs; res[cs]=frag([cs]*n)
print({k:round(v,4) for k,v in res.items()})
mix=[256<<20]*2+[1<<20]*256+[65536]*2048
print('mix total',sum(mix)/G, round(frag(mix),4))
fig,ax=plt.subplots(figsize=(16,6.5))
xs=list(res); ax.semilogx(xs,[res[x] for x in xs],'o-',color='#C0392B',lw=2,base=2)
for x in xs: ax.annotate(f'{res[x]:.3f}',(x,res[x]),xytext=(0,10),textcoords='offset points',ha='center',fontsize=11)
ax.set_xticks(xs); ax.set_xticklabels(['4K','16K','64K','1M','16M','128M','256M','1G'])
ax.set_xlabel('size of each free chunk (1 GiB free in total, block_size 4K)'); ax.set_ylabel('fragmentation_rating')
ax.axhline(frag(mix),color='#2E86C1',ls='--'); ax.text(4096*1.2,frag(mix)+0.03,f'mixed 896 MiB: 2x256M + 256x1M + 2048x64K -> {frag(mix):.3f}',color='#2E86C1',fontsize=12)
ax.set_ylim(-0.05,1.1); ax.grid(alpha=.3)
ax.set_title('Allocator::get_fragmentation_score: 0 = one contiguous chunk, 1 = all free space in 4K pieces',fontsize=13)
fig.tight_layout(); fig.savefig(D+'f06_fragscore.png',dpi=110)
# ---- AVL near-fit vs best-fit
K=1024
free=[(0x10000,0x18000),(0x40000,0x60000),(0x100000,0x108000),(0x200000,0x300000)]
def draw(ax,fr,alloc,title,cursor=None):
    ax.barh(0,0x320000,color='#D5D8DC',height=0.5)
    for s,e in fr: ax.barh(0,e-s,left=s,color='#58D68D',height=0.5)
    for s,e,c in alloc: ax.barh(0,e-s,left=s,color=c,height=0.5,hatch='//',edgecolor='k')
    for s,e in fr: ax.text((s+e)/2,-0.45,f'{(e-s)//K}K',ha='center',va='top',fontsize=11)
    if cursor is not None: ax.axvline(cursor,color='#8E44AD',ls='--'); ax.text(cursor+0x8000,0.3,f'cursor 0x{cursor:x}',color='#8E44AD',fontsize=11,ha='left')
    ax.set_yticks([]); ax.set_ylim(-0.9,0.5); ax.set_xlim(0,0x320000); ax.set_title(title,fontsize=12)
    ax.set_xticks([0,0x100000,0x200000,0x300000]); ax.set_xticklabels(['0','1M','2M','3M'])
fig,axs=plt.subplots(3,1,figsize=(16,9))
draw(axs[0],free,[],'free ranges (green) before allocation; lbas[] cursors start at 0',0)
draw(axs[1],free,[(0x40000,0x50000,'#E74C3C')],'near-fit: want 64K, align = 64K -> cursor lbas[16]; 32K range skipped, take 0x40000, cursor -> 0x50000',0x50000)
draw(axs[2],free,[(0x10000,0x18000,'#F39C12')],'best-fit (free < 4% or largest < 128K): want 32K -> size tree lower_bound{0,32K}: two 32K ranges, lower offset wins -> 0x10000',None)
fig.tight_layout(); fig.savefig(D+'f07_avl.png',dpi=110)
