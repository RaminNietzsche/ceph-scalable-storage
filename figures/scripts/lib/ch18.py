"""Simulation model ch18 (library module, imported by figures/scripts/*.py)."""
import math
H=43200
def dead(s,u): return max(0,s*(1-u/(2*H))-u/(2*H))
def live(s,u): return min(1,s*(1-u/(2*H))+u/(2*H))
s=1.0; t=0
pts={}
while t<80000:
    s=dead(s,2); t+=2
    if t in (600,3600,6*3600,12*3600): pts[t]=round(s,4)
    if s==0: print('zero at',t); break
print(pts, 'cont zero', 86400*math.log(2))
s1h=1.0
for _ in range(1800): s1h=dead(s1h,2)
print('1h dead',s1h)
# election example
sc={'a':1+0+0+1,'b':4,'c':3,'d':3}
# after recovery: c,d histories of a = s1h
print('after recovery a',1+2*s1h+1)
# simple policy sim
def per(n,k): return max(1,n//k)
import itertools
A=[('a%d'%i,-10000) for i in range(100)]
M={'A':dict(A)}
def shuffle(now,thr=300):
    n=sum(len(v) for v in M.values()); p=per(n,len(M)); remap=[]
    for inst,imgs in M.items():
        if len(imgs)<=p: continue
        cut=len(imgs)-p
        for im,mt in sorted(imgs.items()):
            if cut==0: break
            if now-mt>=thr: cut-=1; remap.append((inst,im))
    for inst,im in remap:
        del M[inst][im]
        tgt=min(M,key=lambda k:(len(M[k]),k)); M[tgt][im]=now
def show(tag): print(tag,{k:len(v) for k,v in M.items()})
M['B']={}; shuffle(0); show('B joins t=0')
M['C']={}; shuffle(200); show('C joins t=200')
shuffle(400); show('reshuffle t=400 (if triggered)')
dead_imgs=M.pop('A')
for im in sorted(dead_imgs):
    tgt=min(M,key=lambda k:(len(M[k]),k)); M[tgt][im]=1000
show('A dies t=1000')
