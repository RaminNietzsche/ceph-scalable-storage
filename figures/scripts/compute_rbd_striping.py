#!/usr/bin/env python3
"""Small verification calculator used while writing the chapter text.

Migrated from the v1.0-v1.4 working tree; paths are repository-relative.
Run from anywhere: the script changes into the repository root first.
"""
import os as _os, sys as _sys
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
_os.chdir(_ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, 'figures', 'scripts', 'lib'))
CEPH_CONF = _os.environ.get('CEPH_CONF', '/etc/ceph/ceph.conf')
def mp(off,ln,su,sc,os):
    spo=os//su; out=[]
    while ln>0:
        blockno,blockoff=divmod(off,su); stripeno,pos=divmod(blockno,sc); objset,setpos=divmod(stripeno,spo)
        objno=objset*sc+pos; objoff=setpos*su+blockoff; x=min(ln,su-blockoff)
        out.append((off,objno,objoff,x)); off+=x; ln-=x
    return out
K=1024;M=K*K
for r in mp(M+32*K,256*K,64*K,4,4*M): print(r[0]//K, "obj", r[1], r[2]//K, r[3]//K)
print('default')
for r in mp(3*M,4*M,4*M,1,4*M): print(r[0]//K, "obj", r[1], r[2]//K, r[3]//K)
