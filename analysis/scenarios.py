"""情景计算：线路/社区/全节期、无回答边界、补给情景。只读 data/。"""

import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'data'
Z = 1.6448536269514722


def rd(n):
    with (ROOT / f'{n}.csv').open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def occs(r):
    return [o for o in r['occurrences'].split('+') if o]


def tc(df):
    z = Z
    return (z + (z**3 + z) / 4 / df + (5 * z**5 + 16 * z**3 + 3 * z) / 96 / df**2
            + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384 / df**3)


PERF = {p['occurrence']: p for p in rd('performances')}
FRAME = {r['stratum']: r for r in rd('frame')}
RES = rd('residents')
OCC_ROUTE = {o: p['route'] for o, p in PERF.items()}
OCC_STOP = {o: p['stop'] for o, p in PERF.items()}


def hh_table(rows, strata, route=None, stop=None, metric='any', mode='cc', extra=None):
    """-> {stratum: [(y, m_all, m_answered)]}"""
    out = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for r in rows:
        if r['stratum'] not in strata:
            continue
        h = out[r['stratum']][r['household']]
        h[1] += 1
        ans = r['response'] == 'answered'
        if ans:
            h[2] += 1
        v = set(occs(r))
        if extra and r['record'] in extra:
            v |= extra[r['record']]
        if route:
            v = {o for o in v if OCC_ROUTE[o] == route}
        if stop:
            v = {o for o in v if OCC_STOP[o] == stop}
        hit = bool(v) if metric == 'any' else len(v) >= 2
        if mode == 'upper' and not ans:
            hit = True
        if hit and (ans or mode == 'upper'):
            h[0] += 1
    return out


def ratio_est(vals, covered, N):
    n = len(vals)
    if not n:
        return None
    y = sum(v[0] for v in vals)
    m = sum(v[2] for v in vals)  # cc denominator only
    if m == 0:
        return None
    rate = y / m
    mbar = m / n
    e = [v[0] - rate * v[2] for v in vals]
    eb = sum(e) / n
    s2 = sum((x - eb) ** 2 for x in e) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(max((1 - n / N) * s2 / (n * mbar * mbar), 0)) * covered
    return rate * covered, se, n, y, m


def expand(rows, strata, **kw):
    mode = kw.pop('mode', 'cc')
    tab = hh_table(rows, strata, mode=mode, **kw)
    est = se = 0.0
    parts = []
    for s in strata:
        if s not in tab:
            continue
        cov = int(FRAME[s]['covered'])
        if cov == 0:
            continue
        vals = list(tab[s].values())
        y = sum(v[0] for v in vals)
        if mode == 'upper':
            y += sum(v[1] - v[2] for v in vals)
        res = ratio_est([[y, 0, sum(v[2] for v in vals)]] + [[v[0], 0, v[2]] for v in vals[1:]], cov, int(FRAME[s]['households'])) if False else None
        # proper: recompute with y including unknown for upper
        n = len(vals)
        m = sum(v[2] for v in vals)
        rate = y / m
        mbar = m / n
        e = [v[0] + (v[1] - v[2] if mode == 'upper' else 0) - rate * v[2] for v in vals]
        eb = sum(e) / n
        s2 = sum((x - eb) ** 2 for x in e) / (n - 1)
        sev = math.sqrt(max((1 - n / int(FRAME[s]['households'])) * s2 / (n * mbar * mbar), 0)) * cov
        est += rate * cov
        se += sev ** 2
        parts.append((s, rate * cov, sev, n, y, m))
    return est, math.sqrt(se), parts


def line(name, est, se, df):
    t = tc(df)
    rel = 2 * t * se / est if est else float('inf')
    print(f'{name:42s} {est:8.1f}  se={se:5.1f}  90%CI=({est-t*se:7.1f},{est+t*se:7.1f})  rel={rel:.3f}  '
          f'{"可发布" if rel <= 0.3 else "不可比"}')


print('覆盖名册：', {s: f"{FRAME[s]['covered']}/{FRAME[s]['eligible']}" for s in ['S1', 'S2', 'S3', 'S4']})
COV = sum(int(FRAME[s]['covered']) for s in ['S1', 'S2', 'S3'])
ELIG = sum(int(FRAME[s]['eligible']) for s in FRAME)

print('\n### 社区框·分省层')
for s in ['S1', 'S2', 'S3']:
    for metric in ('any', 'rep'):
        est, se, parts = expand(RES, [s], metric=metric)
        line(f'{s} {metric}', est, se, parts[0][3] - 1)

print('\n### 全节期（S1+S2+S3）')
for metric in ('any', 'rep'):
    est, se, parts = expand(RES, ['S1', 'S2', 'S3'], metric=metric)
    line(f'全节期 {metric}', est, se, sum(p[3] for p in parts) - 3)
    print('   ', [(p[0], round(p[1], 1)) for p in parts])

print('\n### 线路（全节期人口）')
route_est = {}
for rt in ['R1', 'R2', 'R3']:
    for metric in ('any', 'rep'):
        est, se, parts = expand(RES, ['S1', 'S2', 'S3'], route=rt, metric=metric)
        line(f'{rt} {metric}', est, se, sum(p[3] for p in parts) - 3)
        if metric == 'any':
            route_est[rt] = est
print('  线路相加', round(sum(route_est.values()), 1), '全节期', round(expand(RES, ['S1','S2','S3'], metric='any')[0], 1),
      '差', round(sum(route_est.values()) - expand(RES, ['S1','S2','S3'], metric='any')[0], 1))

print('\n### 停靠点（全节期人口）')
for st in ['南街', '西口', '北场']:
    for metric in ('any', 'rep'):
        est, se, parts = expand(RES, ['S1', 'S2', 'S3'], stop=st, metric=metric)
        line(f'{st} {metric}', est, se, sum(p[3] for p in parts) - 3)

print('\n### 已发/请求范围')
for strata, routes, label in [(['S1', 'S2'], {'R1', 'R2'}, 'F1已发 S1+S2 R1+R2'),
                              (['S1', 'S2', 'S3', 'S4'], {'R1', 'R2', 'R3'}, 'F2请求 S1..S4 全路线'),
                              (['S1', 'S2', 'S3'], {'R1', 'R2', 'R3'}, '实际可支持 S1+S2+S3')]:
    tmp = []
    for r in RES:
        x = dict(r)
        x['occurrences'] = '+'.join(o for o in occs(r) if OCC_ROUTE[o] in routes)
        tmp.append(x)
    for metric in ('any', 'rep'):
        est, se, parts = expand(tmp, strata, metric=metric)
        if parts:
            line(f'{label} {metric}', est, se, sum(p[3] for p in parts) - len(parts))

print('\n### 无回答边界（未答按未看 / 按看过）')
for metric in ('any', 'rep'):
    lo = expand(RES, ['S1', 'S2', 'S3'], metric=metric, mode='cc')[0]
    up = expand(RES, ['S1', 'S2', 'S3'], metric=metric, mode='upper')[0]
    print(f'全节期 {metric}: 点={lo:.1f} 上界={up:.1f}')
for rt in ['R1', 'R2', 'R3']:
    lo = expand(RES, ['S1', 'S2', 'S3'], route=rt, metric='any')[0]
    up = expand(RES, ['S1', 'S2', 'S3'], route=rt, metric='any', mode='upper')[0]
    print(f'{rt} any: 点={lo:.1f} 上界={up:.1f}')
for st in ['南街', '西口', '北场']:
    lo = expand(RES, ['S1', 'S2', 'S3'], stop=st, metric='any')[0]
    up = expand(RES, ['S1', 'S2', 'S3'], stop=st, metric='any', mode='upper')[0]
    print(f'{st} any: 点={lo:.1f} 上界={up:.1f}')

print('\n### 联结未决的最大影响')
for label, extra in [('忽略', {}), ('Q005 得一次现场观看(E2或E4)', {'Q005': {'P4'}}),
                     ('Q003 得P3(E3)', {'Q003': {'P3'}}), ('Q011 得P6(E5)', {'Q011': {'P6'}}),
                     ('全部候选采信', {'Q005': {'P4'}, 'Q003': {'P3'}, 'Q011': {'P6'}})]:
    est = expand(RES, ['S1', 'S2', 'S3'], metric='any', extra=extra)[0]
    rep = expand(RES, ['S1', 'S2', 'S3'], metric='rep', extra=extra)[0]
    print(f'{label:28s} any={est:7.1f} rep={rep:7.1f}')

print('\n### 末轮补给情景（加权，原框权重=户数/抽中户；名册权重=10/抽中）')
# 原 S2 权重 40/10=4；名册 2 户 p=.2 -> 10/2=5
def weighted(parts):
    """parts: [(rows[(w,y,m)], N, n)]"""
    num = sum(w * y for rows, N, n in parts for w, y, m in rows)
    den = sum(w * m for rows, N, n in parts for w, y, m in rows)
    r = num / den
    V = 0.0
    for rows, N, n in parts:
        zs = [w * (y - r * m) for w, y, m in rows]
        zb = sum(zs) / n
        V += (1 - n / N) * n / (n - 1) * sum((z - zb) ** 2 for z in zs) / den ** 2
    return r, math.sqrt(V)

# S2 原始 10 户
s2 = defaultdict(lambda: [0, 0])
for r in RES:
    if r['stratum'] == 'S2' and r['response'] == 'answered':
        s2[r['household']][1] += 1
        if occs(r):
            s2[r['household']][0] += 1
s2rows = [(4, y, m) for y, m in s2.values()]
print('S2 原始 10 户: y,m=', [(y, m) for w, y, m in s2rows])
# B1 已回收: RS2-07 1 answered 1 viewer, RS2-09 2 answered 1 viewer
b1 = [(5, 1, 1), (5, 1, 2)]
r, se = weighted([(s2rows, 40, 10), (b1, 10, 2)])
t = tc(10)
print(f'S2 原+B1(合并解释): {r*100:.1f} se={se*100:.1f} rel={2*t*se/r:.3f}')
# B1 完成整户（RS2-07 补上第2人）两种
for lab, extra in [('第2人为未看', [(5, 1, 2)]), ('第2人为看过', [(5, 2, 2)])]:
    pass
b1c = [(5, 1, 2), (5, 1, 2)]
r, se = weighted([(s2rows, 40, 10), (b1c, 10, 2)])
print(f'S2 原+B1(整户补全): {r*100:.1f} rel={2*tc(10)*se/r:.3f}')

# 需要多少户 S2 名册补充才达到 rel<=.3（保持同样比例和户规模）
for k in range(2, 9):
    b = [(10 / k, 1.6, 2.0)] * k
    r, se = weighted([(s2rows, 40, 10), (b, 10, k)])
    print(f'  S2 补 {k} 户: {r*100:.1f} rel={2*tc(10+k-1)*se/r:.3f}')

# S1 原 30 户
s1 = defaultdict(lambda: [0, 0])
for r in RES:
    if r['stratum'] == 'S1' and r['response'] == 'answered':
        s1[r['household']][1] += 1
        if occs(r):
            s1[r['household']][0] += 1
s1rows = [(5, y, m) for y, m in s1.values()]
print('S1 原始', len(s1rows), '户 y/m=', sum(y for w, y, m in s1rows), '/', sum(m for w, y, m in s1rows))
for k in [3]:
    b = [(10 / k, 1.7, 2.0)] * k
    r, se = weighted([(s1rows, 150, 30), (b, 10, k)])
    print(f'S1 原+B2 {k} 户: {r*50:.1f} (人口={r*450:.1f}) rel={2*tc(30+k-1)*se/r:.3f}')

# S4 补给：covered=0，说明
print('S4 covered=0，eligible=73；B3 名册 10 户抽 3，即使全回收也只能描述该 10 户，不能扩到 73 人或社区名册人口。')
print('S4 roster 户人数:', [r['residents'] for r in rd('roster') if r['stratum'] == 'S4'])

print('\n### 现场框')
aud = rd('audits')
units = defaultdict(list)
for a in aud:
    units[(a['round'], a['unit_hint'])].append(a)
print('表单', len(aud), '轮次×单位', len(units), '重复进场', len(aud) - len(units))
print('每 occurrence 不同单位', {p['occurrence']: len({u[1] for u in units if u[0] == [r['round'] for r in rd('rounds') if r['occurrence'] == p['occurrence']][0]}) for p in PERF.values()})
print('采到 B 入口的 occurrence:', [r['occurrence'] for r in rd('rounds') if r['entrance'] == 'B' and r['sampled'] == 'yes'])
print('未采 B 入口:', [r['occurrence'] for r in rd('rounds') if r['entrance'] == 'B' and r['sampled'] == 'no'])
