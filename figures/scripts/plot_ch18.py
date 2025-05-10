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
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch18/'
H=43200
fig,ax=plt.subplots(figsize=(16,6.5))
t=np.arange(0,80001,60)
sd=np.maximum(0,2*np.exp(-t/86400)-1); sl=1-np.exp(-t/86400)
ax.plot(t/3600,sd,color='#c0392b',lw=2,label='link dead from score 1.0: s -> s(1-u/2h) - u/2h')
ax.plot(t/3600,sl,color='#27ae60',lw=2,label='link live from score 0: s -> s(1-u/2h) + u/2h')
for x,y in [(1,0.9184),(6,0.5576),(12,0.2131),(16.64,0)]:
    ax.plot(x,y,'ko'); ax.text(x+0.3,y+0.03,'%gh: %.3f'%(x,y))
ax.axhline(0.5,ls=':',color='gray')
ax.set_xlabel('hours'); ax.set_ylabel('peer score (history)'); ax.set_xlim(0,22)
ax.set_title('ConnectionTracker score with mon_con_tracker_score_halflife = 43200 s: 2 s pings, alpha = u / 86400; dead link reaches 0 after 86400 ln2 = 16.6 h')
ax.legend(loc='center right'); fig.tight_layout(); fig.savefig(D+'f08_score.png',dpi=110)
# f09 election example
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
mons=['a (r0, DC1)','b (r1, DC1)','c (r2, DC2)','d (r3, DC2)','e (r4, tiebreaker)']
s1=[2.0,4.0,3.0,3.0,-1]; s2=[3.837,4.0,4.0,4.0,-1]
for a,s,ttl in [(ax[0],s1,'during: a<->c and a<->d dead (1 h)'),(ax[1],s2,'after links recover: a = 1 + 0.918 + 0.918 + 1')]:
    cols=['#aab7b8']*5; best=max(range(4),key=lambda i:(s[i],-i)); cols[best]='#27ae60'; cols[4]='#c0392b'
    a.bar(range(5),s,color=cols)
    for i,v in enumerate(s): a.text(i,v+0.05 if v>0 else v-0.25,'%.3f'%v if v>0 else '-1 (disallowed)',ha='center')
    a.set_xticks(range(5)); a.set_xticklabels(mons,fontsize=9); a.set_ylim(-1.5,4.6); a.axhline(0,color='k',lw=0.8)
    a.set_title(ttl+'\nleader: %s (classic strategy would pick a: lowest rank)'%mons[best].split()[0])
    a.set_ylabel('connectivity_election_score = sum of live peer scores')
fig.tight_layout(); fig.savefig(D+'f09_election.png',dpi=110)
# f10 simple policy
fig,ax=plt.subplots(figsize=(16,6.5))
steps=['start','B joins t=0','C joins t=200 s\n(B images < 300 s old)','rebalance t=400 s\n(only if timeout > 0)','A dies t=1000 s']
data=[{'A':100},{'A':50,'B':50},{'A':33,'B':50,'C':17},{'A':34,'B':33,'C':33},{'B':50,'C':50}]
col={'A':'#5dade2','B':'#f5b041','C':'#58d68d'}
for i,dd in enumerate(data):
    b=0
    for k in 'ABC':
        v=dd.get(k,0)
        if v: ax.bar(i,v,bottom=b,color=col[k]); ax.text(i,b+v/2,'%s: %d'%(k,v),ha='center',va='center'); b+=v
ax.set_xticks(range(5)); ax.set_xticklabels(steps); ax.set_ylabel('images mapped')
ax.set_title('rbd-mirror SimplePolicy, 100 images: target = floor(n / live instances); only idle images mapped >= 300 s ago may move (migration_throttle)')
fig.tight_layout(); fig.savefig(D+'f10_imagemap.png',dpi=110)
