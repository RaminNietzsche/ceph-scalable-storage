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
import re,matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt,numpy as np
plt.rcParams['font.family']='DejaVu Sans'
def parse(f,key):
    R=[]
    for l in open(f):
        if not l.strip(): continue
        k=int(re.search(key+r'=(\d+)',l).group(1));bw=float(re.search(r'Bandwidth \(MB/sec\):\s+([\d.]+)',l).group(1))
        io=float(re.search(r'Average IOPS:\s+([\d.]+)',l).group(1));lat=float(re.search(r'Average Latency\(s\):\s+([\d.]+)',l).group(1))
        R.append((k,bw,io,lat))
    return np.array(R)
A=parse('figures/data/radosbench.txt','t')
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
a.plot(A[:,0],A[:,2],'o-',color='#2e86c1',label='IOPS');a.set_xscale('log',base=2);a.set_xlabel('rados bench -t (ops in flight)');a.set_ylabel('IOPS',color='#2e86c1')
a2=a.twinx();a2.plot(A[:,0],A[:,3]*1000,'s-',color='#c0392b',label='avg latency');a2.set_ylabel('avg latency (ms)',color='#c0392b')
for k,bw,io,lat in A: a.annotate(f'{io:.0f}',(k,io),xytext=(-12,8),textcoords='offset points',fontsize=8)
a.set_title('4 KiB writes, size-2 pool: IOPS and latency vs concurrency')
b.plot(A[:,0],A[:,0],'--',color='#7f8c8d',label='t (ops in flight)')
b.plot(A[:,0],A[:,2]*A[:,3],'o-',color='#27ae60',label='measured IOPS x avg latency (Little: L = X . R)')
b.set_xscale('log',base=2);b.set_yscale('log',base=2);b.set_xlabel('rados bench -t');b.set_ylabel('concurrency');b.legend()
for k,bw,io,lat in A: b.annotate(f'{io*lat:.2f}',(k,io*lat),xytext=(6,-12),textcoords='offset points',fontsize=8)
b.set_title("Little's law check: IOPS x latency recovers t")
fig.suptitle('Measured on a 3-OSD BlueStore test cluster (Ceph 18.2.7, sparse files on one VM): relative trends only, not hardware numbers')
plt.tight_layout();plt.savefig('figures/ch10/f09_little.png')
B=parse('figures/data/radosbench_bs.txt','b')
fig,a=plt.subplots(figsize=(16,6.5),dpi=110)
a.plot(B[:,0],B[:,1],'o-',color='#e67e22',label='MB/s');a.set_xscale('log',base=2);a.set_xlabel('object size, bytes (rados bench -b, -t 16)');a.set_ylabel('MB/s',color='#e67e22')
a2=a.twinx();a2.plot(B[:,0],B[:,2],'s-',color='#2e86c1');a2.set_ylabel('IOPS',color='#2e86c1')
for k,bw,io,lat in B: a.annotate(f'{bw:.0f} MB/s\n{io:.0f} IOPS\n{lat*1000:.1f} ms',(k,bw),xytext=(-20,12),textcoords='offset points',fontsize=8)
a.set_ylim(0,800);a.set_title('Size sweep at 16 in flight: IOPS-bound below ~64 KiB, bandwidth-bound above ~256 KiB (same test cluster)')
plt.tight_layout();plt.savefig('figures/ch10/f10_bsweep.png')
