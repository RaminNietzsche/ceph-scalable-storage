"""Simulation model ch07 (library module, imported by figures/scripts/*.py)."""
import math
w=0.3; p=0; I=0
hist=[]
for n in range(1,7):
    interval=40
    I=min(interval,300)*w+I*(1-w); p=w+p*(1-w)
    hist.append((n,round(p,4),round(I,2),round(20+p*I,2)))
print(hist)
k=math.log(.5)/3600
# decay over failed_for 30s
print(math.exp(30*k))
# down->out: p=0.657 I=26.28 my_grace at down=600: 
p,I=hist[2][1],hist[2][2]
print('out grace', 600+math.exp(600*k)*I*p)
# max avail
TiB=1<<40
osds=[(4*TiB,0.60)]*10+[(4*TiB,0.80),(8*TiB,0.55)]
tot=sum(s for s,_ in osds)
res=[]
for s,u in osds:
    frac=s/tot; avail=max(0,s*(1-u)-s*(1-0.95)); res.append(avail/frac)
m=min(res)
print('projs TiB',[round(x/TiB,1) for x in res],'min',round(m/TiB,2),'rep3',round(m/3/TiB,2),'ec4+2',round(m/1.5/TiB,2))
raw_free=sum(s*(1-u) for s,u in osds)
print('raw free',round(raw_free/TiB,2),'tot',tot/TiB)
osds2=[(4*TiB,0.60)]*11+[(8*TiB,0.55)]
res2=[max(0,s*(1-u)-s*0.05)/(s/tot) for s,u in osds2]; print('balanced',round(min(res2)/TiB,2),round(min(res2)/3/TiB,2))
