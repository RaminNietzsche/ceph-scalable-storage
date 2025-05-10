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
def varint(v):
    out=[];b=v&0x7f;v>>=7
    while v: out.append(b|0x80); b=v&0x7f; v>>=7
    out.append(b); return bytes(out)
def lowz(v):
    n=0 if v==0 else min(((v&-v).bit_length()-1)//4,3)
    return varint((v>>(n*4)<<2)|n)
def lba(v):
    lzn=0 if v==0 else ((v&-v).bit_length()-1)//4
    t=lzn-3
    if t<0: pos=3;word=7
    elif t<3: v>>=lzn*4;pos=t+1;word=(1<<t)-1
    else: v>>=20;pos=3;word=3
    word|=(v<<pos)&0x7fffffff; v>>=31-pos
    if not v: return word.to_bytes(4,'little')
    word|=0x80000000; out=word.to_bytes(4,'little'); b=v&0x7f; v>>=7
    while v: out+=bytes([b|0x80]); b=v&0x7f; v>>=7
    return out+bytes([b])
for o,l in [(0x12340000,0x10000),(0x1000,0x1000),(0x3a8f05000,0x3000)]:
    print(hex(o),lba(o).hex(' '),hex(l),lowz(l).hex(' '))
for v in [0x10000,0x1000,0x3000,0x400000,300]: print(hex(v),lowz(v).hex(' '),varint(v).hex(' '))
