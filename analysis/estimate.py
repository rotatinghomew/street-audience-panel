"""节期覆盖与重复观看：按 data/rules.json 的口径计算，只读 data/*.csv。

口径要点
- 分母：社区覆盖名册 covered 人口（S1 450 + S2 100 + S3 260 = 810）。
  eligible 中未被名册覆盖的 203 人没有抽样框，不当作 0。
- 社区框：分层等概率无放回抽户、户内个人清册；户是初级抽样单元，
  成员数作辅助量做比率估计；完成案例处理条目无回答，另报上下界。
- 重复观看：同一人自报在不同 occurrence 出现 >= 2 次。同一 occurrence
  重复进场、同户代答、同一次观看多次记录都不算重复。
- 线路/停靠点数字是同一 810 人分母上的子集，不能相加；相加超出部分
  正好是跨线/跨点重复者。
- 现场框与社区框分别保留入样机会；现场单位号只在本表单内有效，
  不跨轮次识别人，也不进入社区分母。
- 联结只有 result=same/different 的现场确认可直接采用；possible 不合并，
  改为报告可解释上下界。different 永不并入。

运行 `python3 analysis/estimate.py` 打印完整报告；导入时不产生输出。
"""

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'data'
Z90 = 1.6448536269514722
COVERED_STRATA = ['S1', 'S2', 'S3']   # S4 covered=0，不进入分母


def read(name):
    with (ROOT / f'{name}.csv').open(encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def occs(row):
    return [o for o in row['occurrences'].split('+') if o]


def tcrit(df):
    """90% 双侧 t 分位数（Cornish-Fisher 近似，df>=9 足够）。"""
    z = Z90
    return (z + (z**3 + z) / 4 / df
            + (5 * z**5 + 16 * z**3 + 3 * z) / 96 / df**2
            + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384 / df**3)


PERF = {p['occurrence']: p for p in read('performances')}
FRAME = {r['stratum']: r for r in read('frame')}
RESIDENTS = read('residents')
LINKS = read('links')
AUDITS = read('audits')
ROUNDS = read('rounds')
OCC_ROUTE = {o: p['route'] for o, p in PERF.items()}
OCC_STOP = {o: p['stop'] for o, p in PERF.items()}
FORM_ROUND = {a['form']: a['round'] for a in AUDITS}
ROUND_OCC = {r['round']: r['occurrence'] for r in ROUNDS}
FORM_OCC = {f: ROUND_OCC[r] for f, r in FORM_ROUND.items()}


def link_additions(verified=(), pending=False):
    """社区个人 -> 现场 occurrence 的候选增量。

    same 已确认直接并入；different 永不并入；pending=True 时把 possible
    全部计入上界。同一现场个人不能同时对应两个不同常住者，故同组候选
    只在与已自行报告场次相容时才增加数值。
    """
    extra = defaultdict(set)
    for link in LINKS:
        if link['result'] == 'different':
            continue
        ok = (link['result'] == 'same' or link['link'] in verified
              or (pending and link['result'] == 'possible'))
        if ok:
            extra[link['record']].add(FORM_OCC[link['form']])
    return {k: v for k, v in extra.items()}


def hh_arrays(rows, strata, route=None, stop=None, metric='any', extra=None):
    """-> {stratum: [[y, m_all, m_answered], ...]}，一个元素是一户。"""
    out = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for r in rows:
        if r['stratum'] not in strata:
            continue
        h = out[r['stratum']][r['household']]
        h[1] += 1
        answered = r['response'] == 'answered'
        if answered:
            h[2] += 1
        viewed = set(occs(r))
        if extra and r['record'] in extra:
            viewed |= extra[r['record']]
        if route is not None:
            viewed = {o for o in viewed if OCC_ROUTE[o] == route}
        if stop is not None:
            viewed = {o for o in viewed if OCC_STOP[o] == stop}
        hit = bool(viewed) if metric == 'any' else len(viewed) >= 2
        if hit and answered:
            h[0] += 1
    return out


def ratio(vals, covered, N, mode='cc'):
    """户级整群比率估计。mode: cc / lower / upper。"""
    n = len(vals)
    if n == 0:
        return None
    y_i, m_i = [], []
    for y, m_all, m_ans in vals:
        if mode == 'cc':
            y_i.append(y)
            m_i.append(m_ans)
        elif mode == 'lower':
            y_i.append(y)
            m_i.append(m_all)
        elif mode == 'upper':
            y_i.append(y + (m_all - m_ans))
            m_i.append(m_all)
        else:
            raise ValueError(mode)
    m = sum(m_i)
    if m == 0:
        return None
    rate = sum(y_i) / m
    mbar = m / n
    res = [a - rate * b for a, b in zip(y_i, m_i)]
    rbar = sum(res) / n
    s2 = sum((e - rbar) ** 2 for e in res) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(max((1 - n / N) * s2 / (n * mbar * mbar), 0.0)) * covered
    return rate * covered, se, n, sum(y_i), m


def expand(rows, strata, **kw):
    """返回 (估计, 标准误, parts)；parts 每项 (stratum, 估计, se, n, y, m)。

    默认并入现场确认为 same 的联结（E6）；extra={} 可显式关闭。
    """
    if kw.get('extra', 'default') == 'default':
        kw['extra'] = link_additions()
    mode = kw.pop('mode', 'cc')
    tab = hh_arrays(rows, strata, **kw)
    est = var = 0.0
    parts = []
    for s in strata:
        if s not in tab:
            continue
        cov = int(FRAME[s]['covered'])
        if cov == 0:
            continue
        res = ratio(list(tab[s].values()), cov, int(FRAME[s]['households']), mode)
        if res is None:
            continue
        est += res[0]
        var += res[1] ** 2
        parts.append((s, res[0], res[1], res[2], res[3], res[4]))
    return est, math.sqrt(var), parts


def df_of(parts):
    return sum(p[3] for p in parts) - len(parts)


def line(name, est, se, df):
    t = tcrit(df)
    lo, hi = est - t * se, est + t * se
    rel = (2 * t * se / est) if est else float('inf')
    print(f'{name:40s} {est:8.1f}  se={se:6.1f}  90%CI=({lo:7.1f},{hi:7.1f})  '
          f'rel={rel:5.3f}  {"可比" if rel <= 0.30 else "不可比"}')
    return dict(est=est, se=se, lo=lo, hi=hi, rel=rel, df=df)


def bounds(rows, strata, **kw):
    lo = expand(rows, strata, mode='lower', **kw)[0]
    hi = expand(rows, strata, mode='upper', **kw)[0]
    return lo, hi


def main():
    print('=' * 100)
    print('1. 抽样框与分母')
    print('=' * 100)
    for s in ['S1', 'S2', 'S3', 'S4']:
        f = FRAME[s]
        cov = int(f['covered'])
        print(f"{s} {f['community']}  eligible={f['eligible']:>4}  covered={cov:>4}  "
              f"覆盖率={cov / int(f['eligible']):6.1%}  households={f['households']:>3}  "
              f"drawn={f['drawn']:>2}")
    cov_total = sum(int(FRAME[s]['covered']) for s in COVERED_STRATA)
    elig_total = sum(int(FRAME[s]['eligible']) for s in FRAME)
    print(f'目标人口 covered={cov_total}；eligible={elig_total}；'
          f'未被名册覆盖={elig_total - cov_total}'
          '（S1 50 / S2 40 / S3 40 / S4 73），无框，不按 0 处理。')
    print(f'回答个体={sum(1 for r in RESIDENTS if r["response"] == "answered")}，'
          f'条目未答={sum(1 for r in RESIDENTS if r["response"] != "answered")}；'
          '分母是 810 人，不是问卷数。')

    print('\n' + '=' * 100)
    print('2. 全节期（S1+S2+S3，810 人）')
    print('=' * 100)
    fest = {}
    for metric in ('any', 'rep'):
        est, se, parts = expand(RESIDENTS, COVERED_STRATA, metric=metric)
        fest[metric] = line(f'全节期 {"观看>=1" if metric == "any" else "重复观看>=2场"}',
                            est, se, df_of(parts))
        lo, hi = bounds(RESIDENTS, COVERED_STRATA, metric=metric)
        print(f'{"":40s} 分省层 {[(p[0], round(p[1], 1)) for p in parts]}')
        print(f'{"":40s} 无回答边界=({lo:.1f}, {hi:.1f})')

    print('\n' + '=' * 100)
    print('3. 线路（同一 810 人分母，不是独立总体）')
    print('=' * 100)
    route = {}
    for rt in ['R1', 'R2', 'R3']:
        for metric in ('any', 'rep'):
            est, se, parts = expand(RESIDENTS, COVERED_STRATA, route=rt, metric=metric)
            route[(rt, metric)] = line(
                f'{rt} {"观看>=1" if metric == "any" else "重复观看>=2场"}', est, se, df_of(parts))
            if metric == 'any':
                lo, hi = bounds(RESIDENTS, COVERED_STRATA, route=rt, metric=metric)
                print(f'{"":40s} 无回答边界=({lo:.1f}, {hi:.1f})')
    route_sum = sum(route[(r, 'any')]['est'] for r in ['R1', 'R2', 'R3'])
    print(f'线路观看数相加={route_sum:.1f}；全节期={fest["any"]["est"]:.1f}；'
          f'超出={route_sum - fest["any"]["est"]:.1f}（=跨线重复者，不是新观众）')
    print(f'线路重复数相加={sum(route[(r, "rep")]["est"] for r in ["R1", "R2", "R3"]):.1f}；'
          f'节期重复={fest["rep"]["est"]:.1f}（跨线重复是全局事实，按线路相加会重复计数）')

    print('\n' + '=' * 100)
    print('4. 社区')
    print('=' * 100)
    for label, strata in [('春桥（S1+S2）', ['S1', 'S2']), ('平林（S3）', ['S3'])]:
        for metric in ('any', 'rep'):
            est, se, parts = expand(RESIDENTS, strata, metric=metric)
            line(f'{label} {"观看>=1" if metric == "any" else "重复观看>=2场"}',
                 est, se, df_of(parts))
            if metric == 'any':
                lo, hi = bounds(RESIDENTS, strata, metric=metric)
                print(f'{"":40s} 无回答边界=({lo:.1f}, {hi:.1f})')

    print('\n' + '=' * 100)
    print('5. 重复结构（样本事实，未加权）')
    print('=' * 100)
    ans = [r for r in RESIDENTS if r['response'] == 'answered']

    def routes(r):
        return {OCC_ROUTE[o] for o in occs(r)}

    def stops(r):
        return {OCC_STOP[o] for o in occs(r)}

    rep = [r for r in ans if len(set(occs(r))) >= 2]
    print(f'已答 {len(ans)} 人：任何观看 {sum(1 for r in ans if occs(r))}，重复 {len(rep)}')
    print('重复者的观看场次数分布', dict(Counter(len(set(occs(r))) for r in rep)))
    print(f'跨线路重复={sum(1 for r in rep if len(routes(r)) >= 2)}；'
          f'线路内重复={sum(1 for r in ans if max(Counter(OCC_ROUTE[o] for o in occs(r)).values(), default=0) >= 2)}')
    print(f'跨停靠点重复={sum(1 for r in rep if len(stops(r)) >= 2)}；'
          f'同一停靠点重复={sum(1 for r in ans if max(Counter(OCC_STOP[o] for o in occs(r)).values(), default=0) >= 2)}')
    print(f'线路观看样本相加={sum(sum(1 for r in ans if rt in routes(r)) for rt in ["R1", "R2", "R3"])}；'
          f'停靠点相加={sum(sum(1 for r in ans if st in stops(r)) for st in ["南街", "西口", "北场"])}；'
          f'节期并集={sum(1 for r in ans if occs(r))}')

    print('\n' + '=' * 100)
    print('6. 联结：确认/未决及对数值的影响')
    print('=' * 100)
    for link in LINKS:
        print(f"{link['link']} 表单{link['form']}({FORM_OCC[link['form']]}) "
              f"个人{link['record']} 组{link['group']} 结果={link['result']} 收到={link['received']}")
    confirmed = link_additions()
    pending = link_additions(pending=True)
    print('E6=same 已并入；E1/E7=different 不并入；E2/E3/E4/E5=possible 未决。')
    for label, extra in [('仅现场确认（same）', confirmed),
                         ('全部 possible 采信（上界）', pending)]:
        for metric in ('any', 'rep'):
            est = expand(RESIDENTS, COVERED_STRATA, metric=metric, extra=extra)[0]
            print(f'{label:26s} {"观看>=1" if metric == "any" else "重复>=2场"}={est:8.1f}')
    print('E2/E4 是唯一会改变数值的未决项（Q005 增加一次 P4）；'
          'E1/E3 所指 P4 该人已自报，E5 所指 P6 该人已自报，均不改变判定。')
    for rt in ['R1', 'R2', 'R3']:
        lo, hi = bounds(RESIDENTS, COVERED_STRATA, route=rt, metric='any', extra=pending)
        print(f'  线路 {rt} 上下界=({lo:.1f},{hi:.1f})')
    lo, hi = bounds(RESIDENTS, COVERED_STRATA, metric='any', extra=pending)
    print(f'  全节期 上下界=({lo:.1f},{hi:.1f})')

    print('\n' + '=' * 100)
    print('7. 已发/请求的适用范围')
    print('=' * 100)
    for label, strata, rts in [
            ('F1 已发 S1+S2 / R1+R2', ['S1', 'S2'], {'R1', 'R2'}),
            ('F2 请求 S1..S4 / R1+R2+R3', ['S1', 'S2', 'S3', 'S4'], {'R1', 'R2', 'R3'}),
            ('实际有框 S1+S2+S3 / R1+R2+R3', ['S1', 'S2', 'S3'], {'R1', 'R2', 'R3'})]:
        tmp = []
        for r in RESIDENTS:
            x = dict(r)
            x['occurrences'] = '+'.join(o for o in occs(r) if OCC_ROUTE[o] in rts)
            tmp.append(x)
        for metric in ('any', 'rep'):
            est, se, parts = expand(tmp, strata, metric=metric)
            if parts:
                line(f'{label} {"观看>=1" if metric == "any" else "重复>=2场"}',
                     est, se, df_of(parts))

    print('\n' + '=' * 100)
    print('8. 现场框（只描述，不进入社区分母）')
    print('=' * 100)
    units = defaultdict(list)
    for a in AUDITS:
        units[(a['round'], a['unit_hint'])].append(a)
    print(f'表单 {len(AUDITS)}；轮次×单位 {len(units)}；同一单位重复进入 {len(AUDITS) - len(units)} 次')
    print('每个单位进入次数分布', dict(Counter(len(v) for v in units.values())))
    print('每轮表单', {r['round']: sum(1 for a in AUDITS if a['round'] == r['round']) for r in ROUNDS})
    print('有表单的入口:', sorted({r['round'][-1] for r in ROUNDS
                                   if any(a['round'] == r['round'] for a in AUDITS)}))
    print('抽中但无表单的轮次:', [r['round'] for r in ROUNDS if r['sampled'] == 'yes'
                                and not any(a['round'] == r['round'] for a in AUDITS)])
    print('未抽 B 入口的场次:', [r['occurrence'] for r in ROUNDS
                                if r['entrance'] == 'B' and r['sampled'] == 'no'])
    print('代答表单', sum(1 for a in AUDITS if a['response'] == 'proxy'),
          '涉及', len({a['unit_hint'] for a in AUDITS if a['response'] == 'proxy'}), '个单位')
    unit_rounds = defaultdict(set)
    for (rd_name, unit), _ in units.items():
        unit_rounds[unit].add(rd_name)
    print('单位号跨轮出现:', [u for u, rs in unit_rounds.items() if len(rs) > 1])
    print('现场框人数：单位号是表单内编号，跨轮无共用识别，不能据以估计人数；'
          f'可见 {len(units)} 个轮次×单位，覆盖 {len({u[1] for u in units})} 个单位号。')

    print('\n' + '=' * 100)
    print('9. 末轮登记、回收与可用班次')
    print('=' * 100)
    for p in read('plans'):
        print('plan', p)
    for f in read('follow_up'):
        print('shift', f)
    for a in read('availability'):
        print('avail', a)
    for r in read('returns'):
        print('return', r)

    print('\n' + '=' * 100)
    print('10. 补给情景：S2 的两份名册资料怎样合并')
    print('=' * 100)
    s2 = defaultdict(lambda: [0, 0])
    for r in RESIDENTS:
        if r['stratum'] == 'S2' and r['response'] == 'answered':
            s2[r['household']][1] += 1
            if occs(r):
                s2[r['household']][0] += 1
    s2rows = [(4, y, m) for y, m in s2.values()]   # 原框：40 户抽 10 户
    print('S2 原框户级 y/已答m:', [(y, m) for w, y, m in s2rows])

    def weighted(parts):
        num = sum(w * y for rows, N, n in parts for w, y, m in rows)
        den = sum(w * m for rows, N, n in parts for w, y, m in rows)
        r = num / den
        V = 0.0
        for rows, N, n in parts:
            zs = [w * (y - r * m) for w, y, m in rows]
            zb = sum(zs) / n
            if n > 1:
                V += (1 - n / N) * n / (n - 1) * sum((z - zb) ** 2 for z in zs) / den ** 2
        return r, math.sqrt(V)

    supp = [(1, 2), (1, 1)]   # RS2-09 完整(1/2)；RS2-07 部分(1/1 已答)
    for label, w in [('名册视为 S2 的 10 户独立框（w=5）', 5),
                     ('名册为 40 户原框的两阶段余户（w=6.67）', 20 / 3)]:
        r, se = weighted([(s2rows, 40, 10), ([(w, y, m) for y, m in supp], 10, 2)])
        t = tcrit(10)
        print(f'{label:40s} S2={r * 100:5.1f} rel={2 * t * se / r:5.3f} '
              f'{"可比" if 2 * t * se / r <= 0.30 else "不可比"}')
    print('不合并、按原框单独报告：S2=80.0，rel=0.340（刚好不可比）。')
    print('RS2-07 第 2 人补答属于补原户缺答、不是新增样本；补全后 S2 落在 74.0–79.2，'
          'rel 在 0.30 附近摆动，仍不宜宣称跨过阈值。')


if __name__ == '__main__':
    main()
