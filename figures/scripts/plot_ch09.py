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
from string import ascii_uppercase, ascii_lowercase, digits, punctuation
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch09/'
def cr(ch):
    if ch in ascii_uppercase: return 2,'#2E86C1'
    if ch in ascii_lowercase: return 1,'#27AE60'
    if ch in digits: return 1,'#F1C40F'
    if ch in punctuation: return 3,'#E67E22'
    return 5,'#8E44AD'
def seq(p): return any(ord(p[i-1])+1==ord(p[i])==ord(p[i+1])-1 for i in range(1,len(p)-1))
def rep(p): return any(p[i-1]==p[i]==p[i+1] for i in range(1,len(p)-1))
pw=['Pa55word','Storage!9','xyz-Ceph7','mon#ستاره']
fig,ax=plt.subplots(figsize=(16,6.5))
for r,p in enumerate(pw):
    left=0
    for ch in p:
        c,col=cr(ch); ax.barh(r,c,left=left,color=col,edgecolor='white'); ax.text(left+c/2,r,ch if ch.isascii() else '?',ha='center',va='center',fontsize=12,color='black')
        left+=c
    s=seq(p); rp=rep(p)
    verdict=('OK' if left>=10 and len(p)>=8 and not s and not rp else 'REJECT')
    why=[]
    if left<10: why.append('credits < 10')
    if len(p)<8: why.append('len < 8')
    if s: why.append('sequential chars')
    if rp: why.append('repetitive chars')
    ax.text(left+0.5,r,f'{left} credits, len {len(p)} -> {verdict}'+(f" ({', '.join(why)})" if why else ''),va='center',fontsize=12,color='#C0392B' if verdict!='OK' else '#1E8449')
ax.axvline(10,color='k',ls='--'); ax.text(10.2,3.62,'PWD_POLICY_MIN_COMPLEXITY = 10',fontsize=11)
ax.set_yticks(range(len(pw))); ax.set_yticklabels([f'#{i+1}' for i in range(len(pw))]); ax.set_xlim(0,46); ax.set_ylim(3.75,-0.6)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color='#2E86C1',label='uppercase 2'),Patch(color='#27AE60',label='lowercase 1'),Patch(color='#F1C40F',label='digit 1'),Patch(color='#E67E22',label='punctuation 3'),Patch(color='#8E44AD',label='other (e.g. non-ASCII) 5')],loc='upper right')
ax.set_xlabel('complexity credits (sum per character)')
ax.set_title('Dashboard PasswordPolicy.check_password_complexity (only when the complexity check is enabled; ? = non-ASCII letter)',fontsize=12)
fig.tight_layout(); fig.savefig(D+'f06_pwdcredit.png',dpi=110)
for p in pw: print(p, sum(cr(c)[0] for c in p), seq(p), rep(p), len(p))
# f08 lockout timeline
fig,ax=plt.subplots(figsize=(16,5))
for k in range(1,12):
    bad=k<=10
    col='#C0392B' if bad else '#8E44AD'
    ax.plot([k],[0],'o',ms=14,color=col)
    ax.text(k,0.25 if k%2 else -0.4,(f'#{k} wrong pwd\ncounter {k-1}->{k}' if bad else '#11 correct pwd\ncounter 10 >= 10\n-> user.enabled = False'),ha='center',fontsize=10)
ax.hlines(0,0.5,11.5,color='#5D6D7E',lw=3); ax.set_ylim(-0.9,0.8); ax.set_yticks([]); ax.set_xticks([])
ax.set_title('ACCOUNT_LOCKOUT_ATTEMPTS = 10: the check runs before the password is verified, so attempt #11 locks the account even with the right password',fontsize=12)
fig.tight_layout(); fig.savefig(D+'f08_lockout.png',dpi=110)
