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
# grade table + temps
fig,(a1,a2)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
for rate,c in ((20,'#4A72C4'),(50,'#C0392B')):
    v=1000000; g=[]
    for i in range(4): v=int(v*(1-rate/100)); g.append(v)
    a1.plot(range(4),g,'o-',color=c,lw=2,label=f'decay_rate={rate}: {g}')
a1.set_xticks(range(4)); a1.set_xticklabels(['i=0 (newest archived)','1','2','3 (oldest)'],fontsize=12)
a1.set_ylabel('grade (micro)',fontsize=13); a1.legend(fontsize=11); a1.set_title('pg_pool_t::calc_grade_table, hit_set_count=4',fontsize=14)
objs=['A: current set','B: current + set0','C: set1 only','D: none']
t1=[1000000,1000000,0,0]; t2=[0,800000,640000,0]
a2.bar(range(4),t1,color='#9EC5FE',edgecolor='k',label='current hit_set: +1000000')
a2.bar(range(4),t2,bottom=t1,color='#FFE08A',edgecolor='k',label='archived (search_last_n=1): +grade(i) of first match')
for i in range(4): a2.text(i,t1[i]+t2[i]+30000,str(t1[i]+t2[i]),ha='center',fontsize=13)
a2.set_xticks(range(4)); a2.set_xticklabels(objs,fontsize=11); a2.legend(fontsize=11)
a2.set_title('agent_estimate_temp examples (decay 20, last_n 1)',fontsize=14)
plt.tight_layout(); plt.savefig('f07_grade.png'); plt.close()
# effort
fig,ax=plt.subplots(figsize=(16,6),dpi=110)
full=np.linspace(0.7,1.05,500)
def eff(f,tgt):
    fm=f*1e6
    if fm>1e6: return 1.0
    if fm<=tgt: return 0
    e=max((fm-tgt)*1e6/(1e6-tgt),100000); e-=e%100000; e=max(e,100000); return e/1e6
for tgt,l,c in ((816000,'agent was IDLE: target 0.80 + slop 0.016','#4A72C4'),(784000,'agent was evicting: target 0.80 - slop','#C0392B')):
    ax.step(full,[eff(f,tgt) for f in full],where='post',lw=2,color=c,label=l)
ax.plot([0.9],[0.4],'ko',ms=9); ax.annotate('full=0.90: over=84000, span=184000 -> 0.4565 -> quantized 0.4',(0.9,0.4),xytext=(0.72,0.62),fontsize=13,arrowprops=dict(arrowstyle='->'))
ax.set_xlabel('full ratio (user objects x avg size / per-PG target)',fontsize=13); ax.set_ylabel('evict_effort',fontsize=13)
ax.legend(fontsize=12,loc='upper left'); ax.grid(alpha=.3)
ax.set_title('PrimaryLogPG::agent_choose_mode evict_effort: min 0.1, quantized to 0.1 steps, 1.0 above 100% full',fontsize=14)
plt.tight_layout(); plt.savefig('f08_effort.png'); plt.close()
# vselector
def f(db):
    prev=1;cur=1;ex=1
    while True:
        nxt=cur*8;thr=prev+cur+nxt;ex+=1
        if db<=thr:
            ct=prev+cur*2; return ex, max(0,db-ct)
        prev+=cur;cur=nxt
xs=np.arange(5,1200,1); ys=[f(x*0.95)[1] for x in xs]
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
ax.plot(xs,ys,lw=2,color='#4A72C4'); ax.plot(xs,xs*0.95,ls='--',color='#999',label='usable DB = 95% of device')
pos={30:(150,700),60:(250,600),120:(350,500),300:(450,400)}
for d in (30,60,120,300):
    e,a=f(d*0.95); ax.plot([d],[a],'o',color='#C0392B',ms=8); ax.annotate(f'{d} GiB: extra_level={e}, db_avail4slow={a:.1f} GiB',(d,a),xytext=pos[d],fontsize=12,arrowprops=dict(arrowstyle='->',color='#C0392B'))
ax.set_xlabel('DB device size (GiB)',fontsize=13); ax.set_ylabel('GiB usable for slow-level data',fontsize=13); ax.legend(fontsize=12); ax.grid(alpha=.3)
ax.set_title('RocksDBBlueFSVolumeSelector (use_some_extra): L0=16M x 64=1G, base=1G, x8, reserved_factor=2',fontsize=14)
plt.tight_layout(); plt.savefig('f09_vsel.png'); plt.close()
# hitset size
fig,ax=plt.subplots(figsize=(16,6),dpi=110)
u=np.logspace(2,6,300)
for per,c in ((1200,'#4A72C4'),(3600,'#C0392B')):
    dur=1200
    ts=np.clip(u*per/dur,1000,100000)
    bits=-ts*math.log(0.0125)/math.log(2)**2
    ax.loglog(u,bits/8/1024,lw=2,color=c,label=f'hit_set_period={per}s (previous set lasted 1200 s)')
ax.axhline(-1000*math.log(0.0125)/math.log(2)**2/8/1024,ls=':',color='#555'); ax.axhline(-100000*math.log(0.0125)/math.log(2)**2/8/1024,ls=':',color='#555')
ax.text(120,1.25,'osd_hit_set_min_size=1000 -> ~1.1 KiB',fontsize=12); ax.text(120,125,'osd_hit_set_max_size=100000 -> ~111 KiB',fontsize=12)
ax.set_xlabel('unique objects inserted in previous HitSet',fontsize=13); ax.set_ylabel('bloom filter size (KiB), fpp=0.05/4',fontsize=13); ax.legend(fontsize=12); ax.grid(alpha=.3,which='both')
ax.set_title('PrimaryLogPG::hit_set_create: target_size = unique x period / duration, clamped; fpp per set = fpp / hit_set_count',fontsize=14)
plt.tight_layout(); plt.savefig('f12_hitset.png'); plt.close()
# lc expire timeline
fig,ax=plt.subplots(figsize=(16,5),dpi=110)
ax.set_xlim(-0.5,33); ax.set_ylim(-1,3)
ax.plot([0.6,0.6],[0,2.2],color='#2E8B57',lw=3); ax.text(0.65,2.3,'PUT: mtime = day 0, 14:24',fontsize=12)
for d in range(0,33,1): ax.axvline(d,color='#eee',lw=1)
ax.axvline(30.6,color='#C0392B',ls='--'); ax.text(30.65,2.3,'mtime + 30 d',fontsize=12,color='#C0392B')
ax.axvline(31,color='#C0392B',lw=3); ax.text(25,1.5,'first LC run with round_to_day(now) - mtime >= 30 d\n-> day 31 window 00:00-06:00',fontsize=12)
ax.axvspan(31,31.25,color='#FFE08A'); ax.axvspan(30,30.25,color='#F1F1F1')
ax.text(27.5,0.4,'day 30 run: base=day30 00:00, diff=29.4 d < 30 -> keep',fontsize=12)
ax.set_xlabel('days',fontsize=13); ax.set_yticks([])
ax.set_title('obj_has_expired(mtime, days=30): base_time = ceph_clock_now().round_to_day() (local midnight), expired when base - mtime >= days x 86400',fontsize=13)
plt.tight_layout(); plt.savefig('f11_lcexpire.png'); plt.close()
