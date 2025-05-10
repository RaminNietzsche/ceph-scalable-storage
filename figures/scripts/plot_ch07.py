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
import math, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch07/'
# f08 laggy EWMA
w=0.3;p=0;I=0;P=[];II=[];G=[]
for n in range(1,9):
    I=40*w+I*(1-w); p=w+p*(1-w); P.append(p); II.append(I); G.append(20+p*I)
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
n=np.arange(1,9)
ax[0].plot(n,P,'o-',color='#c0392b',label='laggy_probability'); ax[0].set_ylim(0,1.05)
a2=ax[0].twinx(); a2.plot(n,II,'s-',color='#2471a3',label='laggy_interval (s)'); a2.set_ylim(0,45)
ax[0].set_xlabel('false "down" events (OSD alive, back after 40 s each)'); ax[0].set_ylabel('laggy_probability',color='#c0392b'); a2.set_ylabel('laggy_interval (s)',color='#2471a3')
ax[0].set_title('EWMA with mon_osd_laggy_weight 0.3\np = 0.3 + 0.7 p ;  I = 0.3 x min(gap, 300) + 0.7 I')
ax[1].bar(n,[20]*8,color='#aab7b8',label='osd_heartbeat_grace 20 s')
ax[1].bar(n,[g-20 for g in G],bottom=20,color='#e67e22',label='+ p x I (own history)')
for x,g in zip(n,G): ax[1].text(x,g+0.8,'%.1f'%g,ha='center')
ax[1].set_xlabel('next failure after N false downs'); ax[1].set_ylabel('seconds before mon marks down')
ax[1].set_title('effective grace (peer term = 0, decay over failed_for ~ 1)\nreset to 0 if next down is > 48 x laggy_halflife = 48 h later')
ax[1].legend(loc='upper left'); fig.tight_layout(); fig.savefig(D+'f08_laggy.png',dpi=110)
# f09 timeline failure->down->out
fig,ax=plt.subplots(figsize=(16,6.5))
ev=[(0,'osd.7 stops answering pings'),(20,'peers on 2 hosts: grace 20 s passed -> MOSDFailure'),(20.5,'reporters by host >= 2 and failed_for >= grace -> marked DOWN (new epoch)'),(620,'down 600 s (+ p x I) -> marked OUT, backfill starts')]
ax.hlines(0,-20,700,color='k')
for i,(t,l) in enumerate(ev):
    ax.plot(t,0,'o',color='#c0392b',ms=9); ax.annotate(l+'\n t = %g s'%t,xy=(t,0),xytext=(t-10 if t<600 else t-240,0.25+0.22*(i%3)),arrowprops=dict(arrowstyle='->'),fontsize=10)
ax.add_patch(Rectangle((20.5,-0.12),600,0.08,color='#f5b041')); ax.text(320,-0.2,'PGs degraded but no data movement (mon_osd_down_out_interval 600 s)',ha='center')
ax.add_patch(Rectangle((0,-0.4),20,0.08,color='#85c1e9')); ax.text(0,-0.48,'heartbeat grace',fontsize=9)
ax.text(320,-0.7,'exceptions: noout / noout on crush node; whole subtree of type "rack" (mon_osd_down_out_subtree_limit) down -> timer reset, never auto-out',ha='center',fontsize=10,color='#7d3c98')
ax.set_ylim(-0.85,1.0); ax.set_xlim(-30,720); ax.set_yticks([]); ax.set_xlabel('seconds')
ax.set_title('from silent OSD to OUT with defaults (healthy history: laggy p = 0)')
fig.tight_layout(); fig.savefig(D+'f09_downout.png',dpi=110)
# f10 max_avail
TiB=1<<40
osds=[(4,0.60)]*10+[(4,0.80),(8,0.55)]
tot=sum(s for s,_ in osds)
proj=[max(0,s*(1-u)-s*0.05)/(s/tot) for s,u in osds]
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
cols=['#5dade2']*10+['#c0392b','#58d68d']
ax[0].bar(range(12),[u*100 for _,u in osds],color=cols); ax[0].axhline(95,ls='--',color='k'); ax[0].text(0,96,'full_ratio 95%')
ax[0].set_xticks(range(12)); ax[0].set_xticklabels(['osd.%d\n%dT'%(i,s) for i,(s,_) in enumerate(osds)],fontsize=8)
ax[0].set_ylabel('% used'); ax[0].set_title('12 OSDs, 52 TiB raw: one 4 TiB OSD at 80%')
ax[1].bar(range(12),proj,color=cols); ax[1].axhline(min(proj),color='#c0392b',ls='--')
ax[1].set_ylim(0,25); ax[1].text(0.2,23.3,'min = %.1f TiB raw -> MAX AVAIL size 3: %.1f TiB, EC 4+2: %.1f TiB'%(min(proj),min(proj)/3,min(proj)/1.5),color='#c0392b')
ax[1].set_xticks(range(12)); ax[1].set_xticklabels(['osd.%d'%i for i in range(12)],fontsize=8)
ax[1].set_ylabel('projected raw TiB until this OSD is full'); ax[1].set_title('get_rule_avail: (avail - size x 5%) / weight share, min over OSDs\n(balanced: 18.2 TiB raw -> 6.1 TiB at size 3)')
fig.tight_layout(); fig.savefig(D+'f10_maxavail.png',dpi=110)
# f11 ratios ladder
fig,ax=plt.subplots(figsize=(16,6.5))
lv=[(70,85,'#58d68d','normal'),(85,90,'#f4d03f','OSD_NEARFULL warning (mon_osd_nearfull_ratio 0.85)'),(90,95,'#eb984e','OSD_BACKFILLFULL: no backfill INTO this OSD (0.90)'),(95,97,'#e74c3c','OSD_FULL: cluster flag full -> client writes blocked (0.95)'),(97,100,'#78281f','osd_failsafe_full_ratio 0.97: OSD itself refuses writes')]
for a,b,c,l in lv:
    ax.add_patch(Rectangle((0,a),1,b-a,color=c)); ax.text(1.05,(a+b)/2,('< 85%%  %s'%l) if a==70 else '%d-%d%%  %s'%(a,b,l),va='center',fontsize=11)
ax.set_xlim(0,4); ax.set_ylim(70,100); ax.set_xticks([]); ax.set_ylabel('% of OSD capacity used')
ax.set_title('fullness ladder (defaults); ratios live in the OSDMap: ceph osd set-nearfull-ratio / set-backfillfull-ratio / set-full-ratio')
fig.tight_layout(); fig.savefig(D+'f11_ratios.png',dpi=110)
