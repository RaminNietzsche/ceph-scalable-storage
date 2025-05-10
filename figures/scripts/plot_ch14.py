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
import numpy as np, math
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch14/'
M=104857600
def N(s): return 1 if s>M else min(1024, M//s)
sizes=[2**k for k in range(12,29)]
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
ax[0].step(sizes,[N(s) for s in sizes],where='post',color='#2471a3',lw=2); ax[0].set_xscale('log',base=2); ax[0].set_yscale('log')
ax[0].axvline(M/1024,ls='--',color='gray'); ax[0].text(M/1024*1.1,600,'100 MiB / 1024 = 100 KiB:\nops cap -> bytes cap',fontsize=9)
for s in [4096,65536,1<<20,4<<20,16<<20,128<<20]:
    ax[0].plot(s,N(s),'ko'); ax[0].text(s,N(s)*1.25,'%s: %d'%(('%dK'%(s>>10)) if s<1<<20 else '%dM'%(s>>20),N(s)),ha='center',fontsize=9)
ax[0].set_xlabel('bytes per op'); ax[0].set_ylabel('ops in flight per Objecter'); ax[0].set_title('in-flight limit = min(1024, floor(100 MiB / size)); size > 100 MiB -> 1')
for lat,c in [(0.002,'#27ae60'),(0.010,'#e67e22'),(0.050,'#c0392b')]:
    ax[1].plot(sizes,[N(s)*s/lat/2**30 for s in sizes],'o-',color=c,label='latency %g ms'%(lat*1000))
ax[1].set_xscale('log',base=2); ax[1].set_yscale('log'); ax[1].set_xlabel('bytes per op'); ax[1].set_ylabel('max GiB/s per client instance (Little)')
ax[1].set_title('throughput ceiling = in-flight x size / latency'); ax[1].legend()
fig.tight_layout(); fig.savefig(D+'f08_budget.png',dpi=110)
# f09 watch liveness
fig,ax=plt.subplots(figsize=(16,6.5))
ax.hlines([1,0],0,60,color='k')
ax.text(-1,1,'client\n(Objecter)',ha='right',va='center'); ax.text(-1,0,'OSD\n(Watch)',ha='right',va='center')
for t in range(0,61,5):
    ok=t<=10
    ax.annotate('',xy=(t+0.8,0.05),xytext=(t,0.95),arrowprops=dict(arrowstyle='->',color='#27ae60' if ok else '#c0392b',ls='-' if ok else ':'))
    ax.text(t,1.08,'ping' if ok else 'lost',ha='center',fontsize=8,color='#27ae60' if ok else '#c0392b')
ax.axvspan(12,60,color='#fadbd8',alpha=0.5); ax.text(13,0.5,'network partition from t = 12 s',fontsize=10)
ax.axvline(40.8,color='#7d3c98',lw=2); ax.text(41.3,0.62,'t = 10 + 30 = 40 s (+ tick):\nOSD drops the watch\n(osd_client_watch_timeout 30)',color='#7d3c98',fontsize=10)
ax.axvline(22,color='#e67e22',lw=1.5,ls='--'); ax.text(22.3,0.3,'objecter_timeout 10 s:\nsession marked laggy,\nnew osdmap requested',color='#e67e22',fontsize=9)
ax.text(30,-0.35,'after reconnect the client sees ENOTCONN from watch_check/error callback and must re-watch and re-read state (notifies in the gap are lost)',ha='center',fontsize=10)
ax.set_ylim(-0.5,1.3); ax.set_xlim(-8,62); ax.set_yticks([]); ax.set_xlabel('seconds (linger ping every objecter_tick_interval = 5 s)')
ax.set_title('watch liveness: last ping that reached the OSD was at t = 10 s')
fig.tight_layout(); fig.savefig(D+'f09_watch.png',dpi=110)
# f10 notify timeout mapping
ms=np.arange(0,4001,1)
eff=[10 if m==0 else (30 if m//1000==0 else m//1000) for m in ms]
fig,ax=plt.subplots(figsize=(16,6.5))
ax.plot(ms,eff,color='#2471a3',lw=2)
ax.annotate('timeout_ms = 0 -> client_notify_timeout = 10 s',xy=(0,10),xytext=(400,14),arrowprops=dict(arrowstyle='->'))
ax.annotate('1..999 ms -> 0 s on the wire -> OSD uses osd_default_notify_timeout = 30 s',xy=(500,30),xytext=(1100,26),arrowprops=dict(arrowstyle='->'))
ax.annotate('1000..1999 ms -> 1 s',xy=(1500,1),xytext=(1600,6),arrowprops=dict(arrowstyle='->'))
ax.set_xlabel('timeout_ms passed to rados_notify2 / IoCtx::notify2'); ax.set_ylabel('effective notify timeout (s)')
ax.set_title('notify timeout is truncated to whole seconds: IoCtxImpl::notify (timeout_ms / 1000) + PrimaryLogPG (0 -> default)')
ax.set_ylim(-1,33); fig.tight_layout(); fig.savefig(D+'f10_notify.png',dpi=110)
