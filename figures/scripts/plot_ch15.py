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
import matplotlib.pyplot as plt
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch15/'
# f06 lock timeline
fig,ax=plt.subplots(figsize=(16,6.5))
ev=[(0,'A','lock exclusive, cookie c1, duration 30 s','ok -> lockers={A/c1, exp 30}','#27AE60'),
    (10,'B','lock exclusive, cookie c2','-EBUSY (exclusive, lockers not empty)','#C0392B'),
    (20,'A','lock again, flags=0','-EEXIST (same locker id, MAY_RENEW unset)','#C0392B'),
    (25,'A','lock, LOCK_FLAG_MAY_RENEW','ok -> old entry erased, exp 55','#27AE60'),
    (60,'B','lock exclusive, cookie c2','read_lock trims A (55 < 60) -> ok, exp 90','#27AE60'),
    (70,'A','lock, LOCK_FLAG_MUST_RENEW','-ENOENT (A/c1 no longer a locker)','#C0392B')]
ax.hlines(1,0,95,color='#2E86C1',lw=4); ax.hlines(0,0,95,color='#8E44AD',lw=4)
ax.text(-2,1,'client A',ha='right',va='center',fontsize=13); ax.text(-2,0,'client B',ha='right',va='center',fontsize=13)
ax.axvspan(0,25,ymin=0.62,ymax=0.72,color='#2E86C1',alpha=.25); ax.axvspan(25,55,ymin=0.62,ymax=0.72,color='#2E86C1',alpha=.45)
ax.axvspan(60,90,ymin=0.28,ymax=0.38,color='#8E44AD',alpha=.35)
for k,(t,c,req,res,col) in enumerate(ev):
    y=1 if c=='A' else 0
    ax.plot([t],[y],'o',ms=12,color=col)
    pos=[(-10,1.6),(5,-0.6),(22,1.6),(5,0.45),(48,-0.6),(62,1.6)][k]
    ax.annotate(f't={t}s  {req}\n{res}',(t,y),xytext=pos,fontsize=10.5,ha='left',arrowprops=dict(arrowstyle='-',color='gray'),bbox=dict(fc='white',ec=col))
ax.set_ylim(-0.9,2.0); ax.set_xlim(-12,100); ax.set_yticks([]); ax.set_xlabel('seconds')
ax.set_title('cls_lock lock_obj on xattr "lock.<name>": exclusive lock, renew flags and lazy expiry (shaded = lock held)',fontsize=13)
fig.tight_layout(); fig.savefig(D+'f06_lock.png',dpi=110)
# f07 omap paging
fig,ax=plt.subplots(figsize=(16,6))
N=2500; mx=1000
calls=[]; start=''; got=0; i=0
while True:
    n=min(mx,N-got); got+=n; more=got<N; calls.append((i,n,more)); i+=1
    if not more: break
ax.barh([f'call {c+1}' for c,_,_ in calls][::-1],[n for _,n,_ in calls][::-1],left=[sum(x[1] for x in calls[:c]) for c,_,_ in calls][::-1],color=['#2E86C1','#27AE60','#E67E22'])
for c,n,more in calls:
    left=sum(x[1] for x in calls[:c])
    ax.text(left+n/2,len(calls)-1-c,f'{n} keys  more={str(more).lower()}\nstart_after = "u_{left-1:04d}"' if c else f'{n} keys  more=true\nstart_after = ""',ha='center',va='center',color='white',fontsize=12)
ax.axvline(1024,color='#C0392B',ls='--'); ax.text(1030,2.35,'osd_max_omap_entries_per_request = 1024 (cap per call)',color='#C0392B',fontsize=11)
ax.set_xlabel('omap keys u_0000 .. u_2499 (filter_prefix "u_", max_to_get 1000)'); ax.set_xlim(0,2600)
ax.set_title('cls_cxx_map_get_vals paging: OSD stops when num >= max_return or bytes >= osd_max_omap_bytes_per_request; more=true only if another matching key exists',fontsize=12)
fig.tight_layout(); fig.savefig(D+'f07_omap.png',dpi=110)
