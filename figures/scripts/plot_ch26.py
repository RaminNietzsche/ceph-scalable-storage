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
fig,ax=plt.subplots(figsize=(16,6),dpi=110)
crc=[('preamble 32',32,'#9EC5FE'),('seg0 hdr2 41 + crc 4',45,'#FFE08A'),('seg1 front 200',200,'#B8E0C2'),('seg3 data 4096',4096,'#D7C4F0'),('epilogue 13',13,'#F4A3A3')]
sec=[('preamble 32 + inline 48 + tag 16',96,'#9EC5FE'),('seg0 inlined: 0',0,'#FFE08A'),('seg1 208 (pad to 16)',208,'#B8E0C2'),('seg3 data 4096',4096,'#D7C4F0'),('epilogue 16 + tag 16',32,'#F4A3A3')]
for y,parts,name in ((1,crc,'crc mode'),(0,sec,'secure mode')):
    left=0
    for l,w,c in parts:
        if w==0: continue
        disp=w if w<1000 else 1000
        ax.barh(y,disp,left=left,color=c,edgecolor='k',height=0.55)
        ax.text(left+disp/2,y,l if disp>150 else '',ha='center',va='center',fontsize=12)
        if disp<=150: ax.annotate(l,(left+disp/2,y+0.28),xytext=(left+disp/2,y+0.45),ha='center',fontsize=11,arrowprops=dict(arrowstyle='-'))
        left+=disp
    tot=sum(w for _,w,_ in parts)
    ax.text(left+20,y,f'{name}: {tot} B on wire (+{tot-4337} B over 4337 logical)',va='center',fontsize=13,weight='bold')
ax.set_yticks([]); ax.set_xlim(0,2000); ax.set_ylim(-0.6,1.8)
ax.set_xlabel('bytes (data segment drawn truncated at 1000)',fontsize=12)
ax.set_title('msgr2.1 MESSAGE frame for header2=41 B, front=200 B, middle=0, data=4096 B (FrameAssembler::get_*_onwire_len)',fontsize=14)
plt.tight_layout(); plt.savefig('f07_onwire.png'); plt.close()
# worker selection
fig,ax=plt.subplots(figsize=(16,5.5),dpi=110)
refs=[0,0,0]; seq=[]
for i in range(10):
    w=min(range(3),key=lambda k:(refs[k],k)); refs[w]+=1; seq.append(w)
    if i==5: refs[1]-=1; seq.append('close')
ax.axis('off')
txt='connection #:   '+'  '.join(f'{i+1:>3}' for i in range(10))
ax.text(0.01,0.84,'NetworkStack::get_worker(): pick the worker with minimum references (ties -> first in vector)\n++references on pick, --references when the connection is released (ms_async_op_threads = 3)',fontsize=13,transform=ax.transAxes)
refs=[0,0,0]; rows=[]
events=['c1','c2','c3','c4','c5','c6','close c5 (w1)','c7','c8','c9','c10']
owner={}
for e in events:
    if e.startswith('close'):
        refs[1]-=1; rows.append((e,'-',refs[:])); continue
    w=min(range(3),key=lambda k:(refs[k],k)); refs[w]+=1; owner[e]=w; rows.append((e,f'msgr-worker-{w}',refs[:]))
for i,(e,w,r) in enumerate(rows):
    y=0.68-i*0.058
    ax.text(0.03,y,e,fontsize=12,transform=ax.transAxes); ax.text(0.2,y,w,fontsize=12,transform=ax.transAxes)
    for k in range(3):
        ax.add_patch(plt.Rectangle((0.42+k*0.18,y-0.01),0.02*r[k],0.04,transform=ax.transAxes,color=['#9EC5FE','#B8E0C2','#FFE08A'][k]))
        ax.text(0.42+k*0.18+0.02*r[k]+0.005,y,str(r[k]),fontsize=11,transform=ax.transAxes)
for k in range(3): ax.text(0.42+k*0.18,0.74,f'references w{k}',fontsize=12,transform=ax.transAxes,weight='bold')
plt.savefig('f10_worker.png'); plt.close()
print(rows[-1])
