"""Inline TeX math ($...$) helpers shared by the book build, the index and the checks."""
from __future__ import annotations

import re

# $...$ with no space just inside the delimiters; a closing $ followed by a digit is not math (prices).
MATH = re.compile(r'\$(?=\S)[^$\n]+?(?<=\S)\$(?!\d)')
_SUP = dict(zip('0123456789+-=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW',
               '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ'))


_SUB = dict(zip('0123456789+-=()aehijklmnoprstuvx', '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ'))


def _sub(e):
    e = e.replace(' ', '')
    return ''.join(_SUB[c] for c in e) if e and all(c in _SUB for c in e) else f'_{e}'


def _sup(e):
    e = e.replace(' ', '')
    return ''.join(_SUP[c] for c in e) if e and all(c in _SUP for c in e) else f'^({e})'


def tex_plain(tex):
    """A plain-text reading of a formula (index, alt text, copy): \\mathrm{GF}(2^8) -> GF(2⁸)."""
    t = tex
    for k, v in (('\\times', '×'), ('\\cdot', '·'), ('\\approx', '≈'), ('\\le', '≤'), ('\\ge', '≥'), ('\\ne', '≠'),
                 ('\\oplus', '⊕'), ('\\sum', 'Σ'), ('\\infty', '∞'), ('\\mu', 'µ'), ('\\lambda', 'λ'), ('\\log', 'log'), ('\\ln', 'ln'),
                 ('\\,', ' '), ('\\_', '\x00'), ('\\%', '%')):
        t = re.sub(re.escape(k) + (r'(?![a-zA-Z])' if k[1:].isalpha() else ''), v, t)
    t = re.sub(r'\\(mathrm|mathit|mathtt|mathbf|text|operatorname)\{([^{}]*)\}', r'\2', t)
    t = re.sub(r'\^\{([^{}]*)\}|\^(\\?\w)', lambda m: _sup(m.group(1) if m.group(1) is not None else m.group(2)), t)
    t = re.sub(r'(?<=[\w)\]Σ])_\{([^{}]*)\}|(?<=[\w)\]Σ])_(\w)', lambda m: _sub(m.group(1) if m.group(1) is not None else m.group(2)), t)
    return re.sub(r'\\[a-zA-Z]+\s*', '', t).replace('{', '').replace('}', '').replace('\x00', '_')
