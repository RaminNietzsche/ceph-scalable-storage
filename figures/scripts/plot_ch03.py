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
import matplotlib.pyplot as plt, numpy as np, sys
from tb import run
from matplotlib.patches import Rectangle
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch03/'
M=1<<20;K=1<<10
def ext(off,ln,os_,su,sc):
    if sc==1: su=os_
    spo=os_//su; out=[]; cur=off; left=ln
    while left>0:
        b=cur//su; sn=b//sc; sp=b%sc; osn=sn//spo; ono=osn*sc+sp
        bs=(sn%spo)*su; bo=cur%su; xl=min(left,su-bo)
        out.append((ono,bs+bo,xl)); cur+=xl; left-=xl
    return out
# f05 striping
fig,(a1,a2)=plt.subplots(2,1,figsize=(16,7.5),dpi=110,gridspec_kw={'height_ratios':[1,1.3]})
for i in range(4):
    a1.add_patch(Rectangle((i*4,0),4,1,fc='#EEF3FB',ec='k'))
    a1.text(i*4+2,1.15,f'rbd_data.<id>.{i:016x}'[:-12]+f'...{i:x}',ha='center',fontsize=11)
for ono,o,l in ext(10*M+512*K,M,4*M,4*M,1):
    a1.add_patch(Rectangle((ono*4+o/M,0),l/M,1,fc='#E67E22',ec='k'))
    a1.annotate('1 MiB at object offset 2.5 MiB (0x280000)',(ono*4+o/M+l/M/2,0.5),xytext=(ono*4-2.5,0.5),fontsize=12,ha='center',va='center',arrowprops=dict(arrowstyle='->'))
a1.set_xlim(-0.2,16.2); a1.set_ylim(-0.2,1.5); a1.axis('off')
a1.set_title('stripe_count=1 (default): write 10.5 MiB~1 MiB -> object 2, offset 0x280000, one extent',fontsize=14)
cols=['#4A72C4','#C0392B','#27AE60','#8E44AD']
r=ext(10*M+512*K,M,4*M,64*K,4)
for i in range(4):
    a2.add_patch(Rectangle((i*4,0),4,1,fc='#EEF3FB',ec='k')); a2.text(i*4+2,1.12,f'object {i}',ha='center',fontsize=12)
for j,(ono,o,l) in enumerate(r):
    a2.add_patch(Rectangle((ono*4+o/M,0),l/M,1,fc=cols[j%4],ec='k',lw=0.5))
for i in range(4):
    a2.text(i*4+2.75,-0.22,'4 x 64K: 0x2a0000-0x2e0000',ha='center',fontsize=11)
    a2.text(i*4+1.3,0.5,'buffer pieces\n'+', '.join(str(i+4*k) for k in range(4)),ha='center',va='center',fontsize=11)
a2.set_xlim(-0.2,16.2); a2.set_ylim(-0.5,1.4); a2.axis('off')
a2.set_title('stripe_unit=64K, stripe_count=4: same write -> 16 pieces, 4 per object (round-robin), object set 0, stripes 42-45',fontsize=14)
plt.tight_layout(); plt.savefig(D+'f05_stripe.png'); plt.close()
# f06 object map size
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
sz=np.logspace(9,16,300)
for osz,c in ((4*M,'#4A72C4'),(1*M,'#27AE60'),(64*K,'#C0392B')):
    n=np.ceil(sz/osz); ok=n<=256e6
    ax.loglog(sz[ok]/2**40,(n[ok]*2/8)/M,lw=2,color=c,label=f'object size {osz//K} KiB')
    lim=256e6*osz; ax.axvline(lim/2**40,ls=':',color=c)
    ax.text(lim/2**40*0.92,0.0012 if osz!=1*M else 0.004,f'max {lim/2**40:.1f} TiB',color=c,fontsize=11,ha='right',rotation=90)
ax.plot([1],[0.0625],'ko',ms=8); ax.annotate('1 TiB / 4 MiB = 262144 objects -> 64 KiB map',(1,0.0625),xytext=(0.004,1.5),fontsize=13,arrowprops=dict(arrowstyle='->'))
ax.set_xlabel('image size (TiB)',fontsize=13); ax.set_ylabel('object map size (MiB), 2 bits/object',fontsize=13)
ax.legend(fontsize=12,loc='upper left'); ax.grid(alpha=.3,which='both')
ax.set_title('librbd object map: BitVector<2>, cap MAX_OBJECT_MAP_OBJECT_COUNT = 256,000,000 objects',fontsize=14)
plt.tight_layout(); plt.savefig(D+'f06_objmap.png'); plt.close()
# f08 fast-diff
S={0:'NONEXISTENT',1:'EXISTS',2:'PENDING',3:'EXISTS_CLEAN'}
C={'NONEXISTENT':'#F2F2F2','EXISTS':'#F5B041','EXISTS_CLEAN':'#85C1E9'}
objs=[('o0',[1,3,3]),('o1',[1,1,3]),('o2',[0,1,3]),('o3',[1,0,0]),('o4',[0,0,0]),('o5',[1,3,1])]
def diff(seq):
    st=None; hist=[]
    for k,m in enumerate(seq):
        last=(k==len(seq)-1)
        if st is None: st='HOLE' if m==0 else ('DATA' if m!=2 else 'DATA_UPDATED')
        elif st=='HOLE':
            if m!=0 and last: st='DATA_UPDATED'
        elif st=='DATA':
            if m==0: st='HOLE_UPDATED'
            elif m!=3: st='DATA_UPDATED'
        elif st=='HOLE_UPDATED':
            if m!=0: st='DATA_UPDATED'
        elif st=='DATA_UPDATED':
            if m==0: st='HOLE_UPDATED'
        hist.append(st)
    return hist
fig,ax=plt.subplots(figsize=(16,7),dpi=110)
cols=['snap1 map','snap2 map','HEAD map']
for r,(nm,seq) in enumerate(objs):
    h=diff(seq); y=len(objs)-1-r
    ax.text(-0.15,y+0.5,nm,ha='right',va='center',fontsize=14)
    for c,m in enumerate(seq):
        ax.add_patch(Rectangle((c*2.2,y+0.08),2,0.84,fc=C[S[m]],ec='k'))
        ax.text(c*2.2+1,y+0.62,S[m],ha='center',fontsize=11); ax.text(c*2.2+1,y+0.28,'-> '+h[c],ha='center',fontsize=10,color='#333')
    res=h[-1]; fc={'DATA':'#D5F5E3','HOLE':'#FFFFFF','DATA_UPDATED':'#F1948A','HOLE_UPDATED':'#BB8FCE'}[res]
    ax.add_patch(Rectangle((6.9,y+0.08),2.6,0.84,fc=fc,ec='k',lw=2)); ax.text(8.2,y+0.5,res+(' (in diff)' if 'UPDATED' in res else ''),ha='center',va='center',fontsize=11)
for c,t in enumerate(cols): ax.text(c*2.2+1,len(objs)+0.2,t,ha='center',fontsize=13,weight='bold')
ax.text(8.2,len(objs)+0.2,'diff state snap1..HEAD',ha='center',fontsize=13,weight='bold')
ax.set_xlim(-1,9.7); ax.set_ylim(-0.1,len(objs)+0.6); ax.axis('off')
ax.set_title('object_map::DiffRequest (diff-iterate): state after each map; HOLE stays HOLE on intermediate snapshots',fontsize=14)
plt.tight_layout(); plt.savefig(D+'f08_fastdiff.png'); plt.close()
# f09 qos
fig,(a1,a2)=plt.subplots(1,2,figsize=(16,7.5),dpi=110)
for (avg,b,bs,idle,lab,c) in ((100,0,1,0,'limit 100, no burst','#4A72C4'),(100,300,2,0,'limit 100, burst 300, burst_seconds 2','#C0392B'),(100,300,2,3,'same, idle for 3 s first','#27AE60')):
    tk,tps,o=run(avg,b,bs,secs=8,idle_until=idle)
    per=[sum(o[i*tps:(i+1)*tps]) for i in range(8)]
    a1.step(range(9),[per[0]]+per,where='pre',lw=2.5,color=c,label=f'{lab}: {per[:6]}')
a1.set_xlabel('second',fontsize=13); a1.set_ylabel('IOs admitted in that second',fontsize=13); a1.legend(fontsize=10.5,loc='upper center',bbox_to_anchor=(0.5,-0.13)); a1.set_ylim(0,650); a1.set_xlim(0,8); a1.grid(alpha=.3)
a1.set_title('saturating client, rbd_qos_schedule_tick_min = 50 ms',fontsize=13)
avgs=[7,30,100]; 
for k,a in enumerate(avgs):
    tick=max(1000//a,50); tps=1000//tick; f=lambda x:int(x/tps*a); t=[f(i)-f(i-1) for i in range(1,tps+1)]
    a2.bar(np.arange(len(t))+k*0.27,t,width=0.27,label=f'avg={a}: tick={tick} ms, {tps} ticks/s, tokens {t[:6]}..., sum={sum(t)}')
a2.set_xlabel('tick index within one second',fontsize=13); a2.set_ylabel('tokens added',fontsize=13); a2.legend(fontsize=10.5,loc='upper center',bbox_to_anchor=(0.5,-0.13)); a2.set_ylim(0,6)
a2.set_title('TokenBucketThrottle::tokens_this_tick: integer spread of avg over ticks',fontsize=13)
plt.tight_layout(); plt.savefig(D+'f09_qos.png'); plt.close()
