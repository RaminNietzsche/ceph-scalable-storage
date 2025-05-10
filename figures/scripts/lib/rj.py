"""Simulation model rj (library module, imported by figures/scripts/*.py)."""
M=0xffffffff
def mix(a,b,c):
    a=(a-b-c)&M; a^=c>>13
    b=(b-c-a)&M; b^=(a<<8)&M
    c=(c-a-b)&M; c^=b>>13
    a=(a-b-c)&M; a^=c>>12
    b=(b-c-a)&M; b^=(a<<16)&M
    c=(c-a-b)&M; c^=b>>5
    a=(a-b-c)&M; a^=c>>3
    b=(b-c-a)&M; b^=(a<<10)&M
    c=(c-a-b)&M; c^=b>>15
    return a,b,c
def rj(s):
    k=s.encode() if isinstance(s,str) else s
    L=len(k); a=b=0x9e3779b9; c=0; i=0; n=L
    while n>=12:
        a=(a+k[i]+(k[i+1]<<8)+(k[i+2]<<16)+(k[i+3]<<24))&M
        b=(b+k[i+4]+(k[i+5]<<8)+(k[i+6]<<16)+(k[i+7]<<24))&M
        c=(c+k[i+8]+(k[i+9]<<8)+(k[i+10]<<16)+(k[i+11]<<24))&M
        a,b,c=mix(a,b,c); i+=12; n-=12
    c=(c+L)&M
    t=k[i:]
    for j,sh in [(10,24),(9,16),(8,8)]:
        if n>j: c=(c+(t[j]<<sh))&M
    for j,sh in [(7,24),(6,16),(5,8),(4,0)]:
        if n>j: b=(b+(t[j]<<sh))&M
    for j,sh in [(3,24),(2,16),(1,8),(0,0)]:
        if n>j: a=(a+(t[j]<<sh))&M
    a,b,c=mix(a,b,c); return c
def frag_make(b,v): return (b<<24)|(v&((0xffffff<<(24-b))&0xffffff))
def frag_contains(f,v):
    b=f>>24; m=(0xffffff<<(24-b))&0xffffff; return (v&m)==(f&0xffffff)
