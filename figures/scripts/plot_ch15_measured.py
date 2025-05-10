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
import json,matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt,numpy as np
plt.rcParams['font.family']='DejaVu Sans'
R=json.load(open('figures/data/cls15.json'))
Ns=sorted({r['N'] for r in R});x=np.arange(len(Ns));w=.38
g=lambda m,k:[next(r[k] for r in R if r['N']==n and r['mode']==m) for n in Ns]
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
a.bar(x-w/2,g('cls','final'),w,color='#27ae60',label='cls numops.add (one op, runs in the PG)')
a.bar(x+w/2,g('rmw','final'),w,color='#c0392b',label='client read omap -> +1 -> write omap')
a.plot(x,g('cls','expected'),'k_',ms=40,mew=2,label='expected = threads x 300')
for i,(f,e) in enumerate(zip(g('rmw','final'),g('rmw','expected'))):
    a.text(i+w/2,f+60,f'lost {e-f}\n({100*(e-f)/e:.0f}%)',ha='center',fontsize=8,color='#c0392b')
a.set_xticks(x);a.set_xticklabels([f'{n} threads' for n in Ns]);a.set_ylabel('final counter value');a.legend(fontsize=9);a.set_title('Correctness: 300 increments per thread on one object')
b.plot(Ns,g('cls','p50'),'o-',color='#27ae60',label='cls p50');b.plot(Ns,g('rmw','p50'),'s-',color='#c0392b',label='read+write p50 (2 round trips)')
b.set_xscale('log',base=2);b.set_yscale('log');b.set_xlabel('threads');b.set_ylabel('ms per increment (median)');b.legend();b.set_title('Median latency per increment (noisy shared VM; p99 spikes ~0.2 s not analysed)')
fig.suptitle('Measured: cls_numops vs client read-modify-write on a 3-OSD BlueStore test cluster, Ceph 18.2.7, python-rados threads')
plt.tight_layout();plt.savefig('figures/ch15/f08_numops.png')
L=json.load(open('figures/data/lua15.json'))
s=[r['size'] for r in L];lm=[r['lua_ms'] for r in L];cm=[r['client_ms'] for r in L]
fig,(a,b)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
a.loglog(s,lm,'o-',color='#8e44ad',label='cls_lua eval_json count_lines (reply 4-6 B)')
a.loglog(s,cm,'s-',color='#2e86c1',label='client read whole object + count (loopback)')
for bw,ls in [(1.25e9,'--'),(0.125e9,':')]:
    a.loglog(s,[c+sz/bw*1e3 for c,sz in zip(cm,s)],ls,color='#2e86c1',label=f'client + transfer at {bw*8/1e9:.0f} Gb/s (derived)')
a.set_xlabel('object size (bytes)');a.set_ylabel('median ms (15 runs)');a.legend(fontsize=8);a.set_title('Counting newlines: server-side Lua vs client')
cross=[sz/((l-c)/1e3)*8/1e9 for sz,l,c in zip(s,lm,cm)]
b.semilogx(s,cross,'o-',color='#e67e22');b.set_xlabel('object size (bytes)');b.set_ylabel('Gb/s')
for sz,v in zip(s,cross): b.annotate(f'{v:.2f} Gb/s',(sz,v),xytext=(4,6),textcoords='offset points',fontsize=8)
b.set_title('Break-even link speed: below it, Lua in the OSD finishes first');b.set_ylim(0,3)
fig.suptitle('Measured on the same test cluster (cls_lua enabled via osd_class_load_list); the Lua run holds the PG for its whole duration')
plt.tight_layout();plt.savefig('figures/ch15/f09_lua.png');print([round(c,2) for c in cross])
