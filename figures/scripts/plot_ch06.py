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
import sys; from rj import *
import math, collections
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch06/'
MiB=1<<20
def loc(off,su,sc,os):
    bn=off//su; sn=bn//sc; pos=bn%sc; spo=os//su; osn=sn//spo; on=osn*sc+pos
    return on,(sn%spo)*su+off%su
# f08 layout
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
cols=plt.cm.tab20.colors
for a,(su,sc,os,title) in zip(ax,[(4*MiB,1,4*MiB,'default layout: su=4M sc=1 object=4M'),(1*MiB,4,4*MiB,'su=1M sc=4 object=4M')]):
    for blk in range(10):
        on,o=loc(blk*MiB,su,sc,os)
        a.add_patch(Rectangle((on*1.2,o/MiB),1,1,color=cols[blk%20],ec='k'))
        a.text(on*1.2+0.5,o/MiB+0.5,'%d-%d MiB'%(blk,blk+1),ha='center',va='center',fontsize=9)
    n=max(loc(b*MiB,su,sc,os)[0] for b in range(10))+1
    for on in range(n):
        a.text(on*1.2+0.5,-0.4,'10000000000.%08x'%on,ha='center',fontsize=8,rotation=0)
    a.add_patch(Rectangle((0,0),0,0))
    a.set_xlim(-0.4,4*1.2+0.2); a.set_ylim(-0.8,4.2); a.set_ylabel('offset inside RADOS object (MiB)')
    a.set_xticks([]); a.set_title(title+'  (10 MiB file, ino 0x10000000000)')
    o9,f9=loc(9*MiB,su,sc,os)
    a.annotate('byte 9 MiB -> object %d at %d MiB'%(o9,f9//MiB), xy=(o9*1.2+1,f9/MiB+0.5), xytext=(3.0,3.7), arrowprops=dict(arrowstyle='->'),fontsize=10)
fig.tight_layout(); fig.savefig(D+'f08_layout.png',dpi=110)
# f09 dirfrag hash space
names=['file_%05d'%i for i in range(100000)]
H=[rj(n) for n in names]
fig,ax=plt.subplots(figsize=(16,6.5))
ax.add_patch(Rectangle((0,2),1,0.6,color='#d5d8dc',ec='k')); ax.text(0.5,2.3,'root frag *  (object 10000000005.00000000)  bits=0',ha='center',va='center')
c=collections.Counter((h>>21)&7 for h in H)
for i in range(8):
    ax.add_patch(Rectangle((i/8,1),1/8,0.6,color=plt.cm.Pastel1(i%9),ec='k'))
    ax.text(i/8+1/16,1.42,'%03d*'%int(bin(i)[2:]) if False else format(i,'03b')+'*',ha='center',fontsize=11)
    ax.text(i/8+1/16,1.25,'.%08x'%frag_make(3,i<<21),ha='center',fontsize=9)
    ax.text(i/8+1/16,1.08,'%d names'%c[i],ha='center',fontsize=9)
for j in range(8):
    x=2/8+j/64
    ax.add_patch(Rectangle((x,0),1/64,0.6,color=plt.cm.Pastel2(j%8),ec='k'))
    ax.text(x+1/128,0.3,format(2,'03b')+format(j,'03b'),rotation=90,ha='center',va='center',fontsize=8)
ax.text(2/8+1/16,-0.15,'frag 010* split again (bits=6) when it passes 10000 entries',ha='center',fontsize=10)
for (n,col),yy in zip([('file_00042','r'),('report.pdf','b'),('IMG_0001.JPG','g')],[2.7,2.95,2.7]):
    h=rj(n); x=(h&0xffffff)/0x1000000
    ax.plot([x,x],[0.65,yy-0.05],color=col,lw=1.5); ax.text(x,yy,'%s\nhash 0x%08x'%(n,h),color=col,ha='center',fontsize=9)
ax.set_xlim(-0.02,1.02); ax.set_ylim(-0.3,3.2); ax.axis('off')
ax.set_title('dentry -> dirfrag: rjenkins(name), only the low 24 bits are the frag space; 3-bit split = hash bits 23..21 (100000 names "file_NNNNN")')
fig.tight_layout(); fig.savefig(D+'f09_dirfrag.png',dpi=110)
# f10 growth
leaves={frag_make(0,0):0}; xs=[];ys=[]; mx=[]
def leaf_of(h):
    for f in leaves:
        if frag_contains(f,h): return f
for idx,h in enumerate(H):
    f=leaf_of(h); leaves[f]+=1
    if leaves[f]>10000:
        b=f>>24; v=f&0xffffff
        del leaves[f]
        for i in range(8): leaves[frag_make(b+3, v|(i<<(24-b-3)))]=0
        for h2 in H[:idx+1]:
            if frag_contains(f,h2): leaves[leaf_of(h2)]+=1
    if idx%250==0: xs.append(idx+1); ys.append(len(leaves)); mx.append(max(leaves.values()))
fig,ax=plt.subplots(figsize=(16,6.5)); ax2=ax.twinx()
ax.step(xs,ys,where='post',color='#2471a3',lw=2,label='dirfrags (leaves)')
ax2.plot(xs,mx,color='#c0392b',lw=1.5,label='largest frag size')
ax2.axhline(10000,ls='--',color='#c0392b'); ax2.text(2000,10300,'mds_bal_split_size 10000',color='#c0392b')
ax2.axhline(15000,ls=':',color='k'); ax2.text(2000,15300,'fast split above 10000 x 1.5 = 15000',color='k')
ax.set_xlabel('entries created in one directory'); ax.set_ylabel('number of dirfrags',color='#2471a3'); ax2.set_ylabel('entries in largest frag',color='#c0392b')
ax.set_title('fragmentation of one directory (instant split, ignoring the 5 s delay): 1 -> 8 at 10001 entries, 8 -> 64 between 79193 and 80693')
ax2.set_ylim(0,17000)
fig.tight_layout(); fig.savefig(D+'f10_fraggrowth.png',dpi=110)
# f11 decay
T=5; k=math.log(.5)/T
fig,ax=plt.subplots(figsize=(16,6.5))
import numpy as np
t=np.linspace(0,40,400)
for r,c in [(1000,'#7f8c8d'),(1500,'#2471a3'),(3000,'#27ae60'),(5000,'#c0392b')]:
    v=r/(-k)*(1-np.exp(k*t)); ax.plot(t,v,color=c,lw=2,label='%d writes/s (steady %d)'%(r,round(r/(-k))))
ax.axhline(10000,ls='--',color='k'); ax.text(30,10400,'mds_bal_split_wr 10000 -> "hot" split',fontsize=10)
for r,tt in [(1500,18.61),(3000,4.47),(5000,2.34)]: ax.plot(tt,10000,'ko'); ax.text(tt+0.3,9300,'%.1f s'%tt)
ax.set_xlabel('seconds of sustained load on one dirfrag'); ax.set_ylabel('DecayCounter value (IWR)')
ax.set_title('DecayCounter with half-life 5 s: steady value = rate x 5 / ln 2 = rate x 7.21; split_wr reached only above 1386.3 writes/s')
ax.legend(loc='lower right'); fig.tight_layout(); fig.savefig(D+'f11_decay.png',dpi=110)
