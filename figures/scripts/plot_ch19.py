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
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, numpy as np
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch19/'
def np2(n,d='nearest'):
    v=int(n)
    if v>0 and v&(v-1)==0: return v>>1 if d=='down' else v
    v-=1
    for s in (1,2,4,8,16): v|=v>>s
    v+=1; x=v>>1
    return v if d=='up' else x if d=='down' else (x if (v-n)>(n-x) else v)
# f05
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
xs=np.linspace(1,600,1200); ax[0].plot(xs,[np2(x) for x in xs],color='#2E86C1',lw=2,label='nearest_power_of_two(target)')
ax[0].plot(xs,xs,'--',color='gray',label='y = target')
for p in (32,64,128,256): ax[0].axvline(p*1.5,color='#E67E22',ls=':',lw=1)
ax[0].plot([100],[128],'o',color='#C0392B',ms=9); ax[0].annotate('target 100 -> 128\n(|128-100|=28 < |100-64|=36)',(100,128),xytext=(160,40),fontsize=12,arrowprops=dict(arrowstyle='->'))
ax[0].set_xlabel('pool_pg_target (per replica)'); ax[0].set_ylabel('final pg_num'); ax[0].set_title('Quantization: midpoints 1.5*2^k (dotted)'); ax[0].legend(loc='upper left'); ax[0].grid(alpha=.3)
cur=32; fin=[16,32,64,128,256]; thr=3.0
cols=['#27AE60' if (f>cur*thr or f<cur/thr) else '#95A5A6' for f in fin]
ax[1].bar([str(f) for f in fin],fin,color=cols); ax[1].set_ylim(-15,280)
ax[1].axhline(cur*thr,color='#C0392B',ls='--'); ax[1].text(0,cur*thr+4,'scale up if > 32*3 = 96',color='#C0392B',fontsize=12)
ax[1].axhline(cur/thr,color='#8E44AD',ls='--'); ax[1].text(-0.4,cur/thr-9,'scale down if < 32/3 = 10.7',color='#8E44AD',fontsize=12)
ax[1].set_title('Threshold 3.0, current pg_num 32: only green would apply'); ax[1].set_xlabel('final_pg_target'); ax[1].set_ylabel('PGs')
fig.suptitle('pg_autoscaler (v20.2.0): power-of-two rounding and the 3x hysteresis',fontsize=15); fig.tight_layout(); fig.savefig(D+'f05_pow2.png',dpi=110)
# f06 knapsack
A=(100,3); B=(180,3); pg_left=1000
def g(t,s):
    dn=np2(t,'down')*s; up=np2(t,'up')*s; tt=t*s
    return dn,up,abs(dn-tt),abs(up-tt)
a=g(*A); b=g(*B); base=a[0]+b[0]; budget=pg_left-base
opts=[]
for ua in (0,1):
  for ub in (0,1):
    extra=ua*(a[1]-a[0])+ub*(b[1]-b[0]); cost=(a[3] if ua else a[2])+(b[3] if ub else b[2])
    opts.append((f"A {'up' if ua else 'down'} / B {'up' if ub else 'down'}",extra,cost,extra<=budget))
print(a,b,base,budget,opts)
fig,ax=plt.subplots(figsize=(16,6.5))
names=[o[0] for o in opts]; costs=[o[2] for o in opts]
c=['#BDC3C7' if not o[3] else '#2E86C1' for o in opts]
best=min([o for o in opts if o[3]],key=lambda o:(o[2],-o[1]))
c[opts.index(best)]='#27AE60'
bars=ax.bar(names,costs,color=c)
for o,bb in zip(opts,bars): ax.text(bb.get_x()+bb.get_width()/2,o[2]+5,f"cost {o[2]}\nextra PG {o[1]}"+("" if o[3] else f"\n> budget {budget}"),ha='center',fontsize=12)
ax.set_ylabel('total |rounded - target| (PG replicas)'); ax.set_ylim(0,max(costs)*1.35)
ax.set_title(f'Knapsack rounding (v21.2.0 Umbrella): pool A target 100x3, pool B 180x3, pg_left {pg_left}, base {base}, budget {budget}  -> green = chosen',fontsize=12)
fig.tight_layout(); fig.savefig(D+'f06_knap.png',dpi=110)
# f07 deviation
w=[1,1,1,1,2,2]; pgs=[55,41,50,46,100,92]; tot=sum(pgs); ppw=tot/sum(w)
def dev(p): return [pi-wi*ppw for pi,wi in zip(p,w)]
def score(p): return sum((d/(wi*ppw))**2*wi for d,wi in zip(dev(p),w))
steps=[list(pgs)]; p=list(pgs)
while True:
    d=dev(p); o=max(range(6),key=lambda i:d[i]); u=min(range(6),key=lambda i:d[i])
    if d[o]<=5 and d[u]>=-5: break
    p[o]-=1; p[u]+=1; steps.append(list(p))
print(tot,ppw,[dev(s) for s in steps],[round(score(s),5) for s in steps])
fig,ax=plt.subplots(figsize=(16,6.5)); x=np.arange(6); wd=0.8/len(steps)
for k,s in enumerate(steps):
    ax.bar(x+k*wd,dev(s),wd,label=f'after {k} upmap(s): bal_score={score(s):.4f}',color=['#C0392B','#E67E22','#27AE60'][k%3])
ax.axhline(5,color='k',ls='--'); ax.axhline(-5,color='k',ls='--'); ax.text(5.3,5.3,'max_deviation = 5',fontsize=12)
ax.set_xticks(x+wd*(len(steps)-1)/2); ax.set_xticklabels([f'osd.{i}\nw={w[i]} target={w[i]*ppw:.0f}' for i in range(6)])
ax.set_ylabel('deviation = pgs - weight*pgs_per_weight'); ax.legend(); ax.grid(axis='y',alpha=.3)
ax.set_title(f'calc_pg_upmaps: {tot} PG replicas, total weight {sum(w)}, pgs_per_weight {ppw:.0f}')
fig.tight_layout(); fig.savefig(D+'f07_dev.png',dpi=110)
