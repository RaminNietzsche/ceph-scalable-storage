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
exp=[0]*512; log=[0]*256; x=1
for i in range(255):
    exp[i]=x; log[x]=i; x<<=1
    if x&0x100: x^=0x11d
for i in range(255,512): exp[i]=exp[i-255]
def mul(a,b): return 0 if a==0 or b==0 else exp[log[a]+log[b]]
def inv(a): return exp[255-log[a]]
k=4;m=6
rs=[[0]*k for _ in range(m)]
for i in range(k): rs[i][i]=1
gen=1
for i in range(k,m):
    p=1
    for j in range(k): rs[i][j]=p; p=mul(p,gen)
    gen=mul(gen,2)
ca=[[0]*k for _ in range(m)]
for i in range(k): ca[i][i]=1
for i in range(k,m):
    for j in range(k): ca[i][j]=inv(i^j)
print('rs',[[hex(v) for v in r] for r in rs[k:]])
print('cauchy',[[hex(v) for v in r] for r in ca[k:]])
print('exp0-15',[hex(exp[i]) for i in range(16)])
print('log1-16',[log[i] for i in range(1,17)])
print('mul(0x53,0xCA)',hex(mul(0x53,0xca)), log[0x53],log[0xca],(log[0x53]+log[0xca])%255)
for c in (2,0x8e):
    lo=[mul(c,n) for n in range(16)]; hi=[mul(c,n<<4) for n in range(16)]
    print('tbl',hex(c),' '.join('%02x'%v for v in lo),'|',' '.join('%02x'%v for v in hi))
b=0xB7; print('b',hex(b),'lo',hex(mul(2,b&15)),'hi',hex(mul(2,b&0xf0)),'xor',hex(mul(2,b&15)^mul(2,b&0xf0)),'direct',hex(mul(2,b)))
D=[0x37,0x5c,0xa1,0x0f]
for name,M in (('rs',rs),('ca',ca)):
    P=[0,0]
    for r in range(2):
        for j in range(k): P[r]^=mul(M[k+r][j],D[j])
    print(name,'P',[hex(v) for v in P])
    new=0xa5; d=D[1]^new
    Pn=[P[r]^mul(M[k+r][1],d) for r in range(2)]
    D2=D[:]; D2[1]=new; Pf=[0,0]
    for r in range(2):
        for j in range(k): Pf[r]^=mul(M[k+r][j],D2[j])
    print(name,'delta',hex(d),'Pn',[hex(v) for v in Pn],'full',[hex(v) for v in Pf])
# rs matrix singularity check: all 4x4 submatrices invertible?
import itertools
def det_inv(Mx):
    n=len(Mx); A=[r[:] for r in Mx]
    for c in range(n):
        piv=next((r for r in range(c,n) if A[r][c]),None)
        if piv is None: return False
        A[c],A[piv]=A[piv],A[c]; iv=inv(A[c][c]); A[c]=[mul(iv,v) for v in A[c]]
        for r in range(n):
            if r!=c and A[r][c]:
                f=A[r][c]; A[r]=[A[r][t]^mul(f,A[c][t]) for t in range(n)]
    return True
for name,M in (('rs',rs),('ca',ca)):
    bad=[s for s in itertools.combinations(range(m),k) if not det_inv([M[i] for i in s])]
    print(name,'singular subsets',len(bad))
# big check rs 10+4 etc
def gen_rs(k,m):
    M=[[0]*k for _ in range(k+m)]
    for i in range(k): M[i][i]=1
    g=1
    for i in range(k,k+m):
        p=1
        for j in range(k): M[i][j]=p; p=mul(p,g)
        g=mul(g,2)
    return M
for (kk,mm) in ((4,2),(6,3),(8,3),(10,4),(8,4),(12,4)):
    M=gen_rs(kk,mm); n=kk+mm
    import random
    subs=list(itertools.combinations(range(n),kk))
    bad=sum(1 for s in subs if not det_inv([M[i] for i in s]))
    print('rs',kk,mm,'subsets',len(subs),'singular',bad)
print('---decode')
M=gen_rs(4,2); rows=[0,2,4,5]
B=[M[r][:] for r in rows]
n=4; A=[B[i][:]+[1 if i==j else 0 for j in range(n)] for i in range(n)]
for c in range(n):
    piv=next(r for r in range(c,n) if A[r][c]); A[c],A[piv]=A[piv],A[c]
    iv=inv(A[c][c]); A[c]=[mul(iv,v) for v in A[c]]
    for r in range(n):
        if r!=c and A[r][c]:
            f=A[r][c]; A[r]=[A[r][t]^mul(f,A[c][t]) for t in range(2*n)]
Inv=[r[n:] for r in A]
print('inv rows for D1,D3',[[hex(v) for v in Inv[1]],[hex(v) for v in Inv[3]]])
surv=[0x37,0xa1,0xc5,0x49]
for idx in (1,3):
    v=0
    for j in range(4): v^=mul(Inv[idx][j],surv[j])
    print('D%d'%idx,hex(v))
print('inv(6)',hex(inv(6)),'inv(0xa)',hex(inv(0xa)))
Pp=0xc5^0x37^0xa1; Qp=0x49^0x37^mul(4,0xa1)
print('Pp',hex(Pp),'4D2',hex(mul(4,0xa1)),'Qp',hex(Qp),'2Pp',hex(mul(2,Pp)),'sum',hex(Qp^mul(2,Pp)),'D3',hex(mul(0xdd,Qp^mul(2,Pp))),'D1',hex(Pp^mul(0xdd,Qp^mul(2,Pp))))
