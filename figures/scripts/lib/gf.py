"""Simulation model gf (library module, imported by figures/scripts/*.py)."""
EXP=[0]*512; LOG=[0]*256; x=1
for i in range(255):
    EXP[i]=x; LOG[x]=i; x<<=1
    if x&0x100: x^=0x11d
for i in range(255,512): EXP[i]=EXP[i-255]
def mul(a,b): return 0 if a==0 or b==0 else EXP[LOG[a]+LOG[b]]
def inv(a): return EXP[255-LOG[a]]
def rs_matrix(n,k):
    a=[[1 if i==j else 0 for j in range(k)] for i in range(k)]
    gen=1
    for i in range(k,n):
        p=1; row=[]
        for j in range(k): row.append(p); p=mul(p,gen)
        a.append(row); gen=mul(gen,2)
    return a
def matvec(A,v):
    out=[]
    for r in A:
        s=0
        for c,x in zip(r,v): s^=mul(c,x)
        out.append(s)
    return out
def invert(M):
    n=len(M); A=[r[:]+[1 if i==j else 0 for j in range(n)] for i,r in enumerate(M)]
    for c in range(n):
        p=next(r for r in range(c,n) if A[r][c]); A[c],A[p]=A[p],A[c]
        iv=inv(A[c][c]); A[c]=[mul(iv,x) for x in A[c]]
        for r in range(n):
            if r!=c and A[r][c]:
                f=A[r][c]; A[r]=[x^mul(f,y) for x,y in zip(A[r],A[c])]
    return [r[n:] for r in A]
