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
P=0x82F63B78
T=[]
for i in range(256):
    c=i
    for _ in range(8): c=(c>>1)^(P if c&1 else 0)
    T.append(c)
def crc(seed,data):
    c=seed
    for b in data: c=(c>>8)^T[(c^b)&0xff]
    return c
# turbo table
tab=[[crc(1<<b,b'\0') for b in range(32)]]
for r in range(1,32):
    prev=tab[-1]; row=[]
    for b in range(32):
        x=prev[b]; y=0
        for j in range(32):
            if x>>j&1: y^=prev[j]
        row.append(y)
    tab.append(row)
print('row0 first4',[hex(v) for v in tab[0][:4]])
def zeros(c,n):
    rem=n&15; n>>=4; r=4; muls=0
    while n:
        if n&1:
            c1=0; j=0; cc=c
            while cc: 
                if cc&1: c1^=tab[r][j]
                cc>>=1; j+=1
            c=c1; muls+=1
        n>>=1; r+=1
    if rem: c=crc(c,b'\0'*rem)
    return c,muls
d=crc(0xffffffff,b'\0'*4096); z=zeros(0xffffffff,4096)
print('4096 zeros direct',hex(d),'turbo',hex(z[0]),'muls',z[1])
z2=zeros(0xffffffff,65536+4096+5); print('69637 zeros',hex(z2[0]),hex(crc(0xffffffff,b'\0'*69637)),'muls',z2[1])
buf=b'ceph-bluestore-blob-'*50
c0=crc(0,buf); cm=crc(0xffffffff,buf)
adj=c0 ^ crc(0^0xffffffff,b'\0'*len(buf))
print('len',len(buf),'crc seed0',hex(c0),'seed-1',hex(cm),'adjusted',hex(adj))
print('check value 123456789 std (with xorout)',hex(crc(0xffffffff,b'123456789')^0xffffffff))
