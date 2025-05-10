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
S=[0]*5+[640000]*2+[1000000]*2+[1800000]
cb=lambda v:v.bit_length(); n=len(S)
bins=[0,20,21]; cnt=[sum(1 for s in S if cb(s)==b) for b in bins]
def pos(b): return sum(1 for s in S if cb(s)<b)*10**6//n, sum(1 for s in S if cb(s)<=b)*10**6//n
fig,axs=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
for ax,mode in zip(axs,('main','fix')):
    cols=[];
    for b in bins:
        lo,up=pos(b)
        keep=(10**6-up>=400000) if mode=='main' else (lo>=400000)
        cols.append('#5CB85C' if keep else '#D9534F')
    x=range(3); ax.bar(x,cnt,color=cols,edgecolor='k')
    for i,b in enumerate(bins):
        lo,up=pos(b); ax.text(i,cnt[i]+0.15,f'lower={lo}\nupper={up}',ha='center',fontsize=12)
    ax.set_xticks(list(x)); ax.set_xticklabels(['bin 0\n(temp 0: D)','bin 20\n(640000 C, 1000000 A)','bin 21\n(1800000: B)'],fontsize=12)
    ax.set_ylim(0,7.5); ax.set_ylabel('samples in temp_hist',fontsize=13)
    t='main: keep if 1e6 - upper >= effort' if mode=='main' else 'proposed (ceph-devel 2017): keep if lower >= effort'
    ax.set_title(t+'\n(evict_effort = 400000; green=keep, red=evict)',fontsize=13)
    a2=ax.twinx(); cum=[pos(b)[1]/1e6 for b in bins]; a2.plot(list(x),cum,'ko-',lw=1.5,label='cumulative share (upper)')
    a2.axhline(0.4 if mode=='fix' else 0.6,ls='--',color='#555'); a2.set_ylim(0,1.15); a2.set_ylabel('cumulative share',fontsize=12)
    a2.text(2.35,(0.4 if mode=='fix' else 0.6)+0.02,'lower=0.4' if mode=='fix' else 'upper=0.6',fontsize=11,ha='right')
    a2.legend(loc='upper left',fontsize=11)
plt.tight_layout(); plt.savefig('figures/ch16/f13_evictinv.png')
