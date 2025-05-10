"""Simulation model ch20 (library module, imported by figures/scripts/*.py)."""
import numpy as np
def bucket(v,minv,quant,nb):
    if v<minv: return 0
    q=(v-minv)//quant
    for i in range(1,nb):
        if q < (1<<(i-1)): return i
    return nb-1
def rng(i,minv,quant):
    if i==0: return None
    lo=0 if i==1 else minv+(1<<(i-2))*quant
    return lo, minv+(1<<(i-1))*quant-1
def prom_rate(ts,vs,t_eval,win):
    # Prometheus extrapolatedRate (counter), simplified port
    sel=[(t,v) for t,v in zip(ts,vs) if t_eval-win < t <= t_eval]
    if len(sel)<2: return None
    inc=0; prev=sel[0][1]
    for t,v in sel[1:]:
        inc += v-prev if v>=prev else v
        prev=v
    t0,t1=sel[0][0],sel[-1][0]; ds=t0-(t_eval-win); de=t_eval-t1
    sd=t1-t0; avg=sd/(len(sel)-1); thr=avg*1.1
    if ds>=thr: ds=avg/2
    if inc>0 and sel[0][1]>=0:
        dz=sd*(sel[0][1]/inc)
        if dz<ds: ds=dz
    if de>=thr: de=avg/2
    return inc*((sd+ds+de)/sd)/win
def predict_linear(ts,vs,t_eval,ahead):
    t=np.array(ts)-t_eval; v=np.array(vs); b,a=np.polyfit(t,v,1); return a+b*ahead
if __name__=='__main__':
    for lat_us in (50,150,1500,30000,2_000_000):
        b=bucket(lat_us*1000,0,100000,32); print('lat',lat_us,'us ->',b,rng(b,0,100000))
    for sz in (0,511,512,4096,65536,4*2**20):
        b=bucket(sz,0,512,32); print('size',sz,'->',b,rng(b,0,512))
    print('last lat bucket starts at s', (1<<29)*100000/1e9)
    # flapping: scrape 15s, osd flaps
    ts=np.arange(0,600,15); up=np.ones(len(ts))
    for k in (22,25,28,31,34,37,39): up[k]=0
    r=prom_rate(list(ts),list(up),ts[-1],300); print('flap rate*60',r*60 if r else r)
    pg=[92,95,98,100,101,103,104,106,110,141]; a=np.mean(pg); print('avg',a,[round((p-a)/a,3) for p in pg])
    t=np.arange(0,48*3600+1,600); v=0.70+0.08*t/(48*3600)
    print('pred',predict_linear(list(t),list(v),t[-1],5*86400))
