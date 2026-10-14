from decimal import Decimal

from django import template

from facturacion import motor

register = template.Library()


@register.filter
def clp(v):
    """12345 → $12.345 (negativos entre signo menos)."""
    if v in (None, ''):
        return '—'
    n = int(Decimal(v))
    return motor.fmt_clp(n) if n >= 0 else '−' + motor.fmt_clp(-n)


@register.filter
def num(v, dec=2):
    if v in (None, ''):
        return '—'
    t = f'{Decimal(v):,.{int(dec)}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return t.rstrip('0').rstrip(',') if ',' in t else t


@register.filter
def uf(v):
    return '—' if v in (None, '') else motor.fmt_uf(Decimal(v))


@register.filter
def fecha(d):
    return d.strftime('%d-%m-%Y') if d else '—'


@register.filter
def mes(d):
    return f'{motor.MESES[d.month]} {d.year}' if d else '—'


@register.filter
def graves(advertencias):
    return [a for a in advertencias if not str(a).startswith('Nota:')]


@register.filter
def pct(v):
    """0.02 → 2 %"""
    if v in (None, ''):
        return '—'
    t = f'{Decimal(v) * 100:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
    return t + ' %'
