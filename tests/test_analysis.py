from collections import defaultdict
import unittest

from inspect_inputs import read_tables
from analysis.estimate import (
    COVERED_STRATA, FRAME, RESIDENTS, expand, link_additions, occs, tcrit,
)


class Denominators(unittest.TestCase):
    def test_frame_is_community_roster_not_questionnaires(self):
        # 分母只能是 covered 人口；eligible 中未覆盖者无框，S4 无覆盖人口。
        self.assertEqual(sum(int(FRAME[s]['covered']) for s in COVERED_STRATA), 810)
        self.assertEqual(int(FRAME['S4']['covered']), 0)
        covered = sum(int(FRAME[s]['covered']) for s in FRAME)
        self.assertEqual(covered, 810)
        self.assertLess(covered, sum(int(FRAME[s]['eligible']) for s in FRAME))

    def test_s4_never_enters_estimates(self):
        est, _, parts = expand(RESIDENTS, COVERED_STRATA, metric='any')
        self.assertNotIn('S4', [p[0] for p in parts])
        est4, _, parts4 = expand(RESIDENTS, ['S4'], metric='any')
        self.assertEqual(parts4, [])
        self.assertEqual(est4, 0.0)

    def test_completed_cases_do_not_count_unknown_as_unseen(self):
        # 未答条目既不是观看也不是未看：完成案例分母只含已答成员。
        answered = sum(1 for r in RESIDENTS if r['response'] == 'answered')
        unknown = sum(1 for r in RESIDENTS if r['response'] != 'answered')
        self.assertEqual(answered + unknown, len(RESIDENTS))
        for r in RESIDENTS:
            if r['response'] != 'answered':
                self.assertEqual(occs(r), [])


class NoDoubleCounting(unittest.TestCase):
    def test_route_and_stop_cannot_be_summed(self):
        fest = expand(RESIDENTS, COVERED_STRATA, metric='any')[0]
        by_route = sum(expand(RESIDENTS, COVERED_STRATA, route=r, metric='any')[0]
                       for r in ['R1', 'R2', 'R3'])
        by_stop = sum(expand(RESIDENTS, COVERED_STRATA, stop=s, metric='any')[0]
                      for s in ['南街', '西口', '北场'])
        self.assertGreater(by_route, fest)
        self.assertGreater(by_stop, fest)
        # 跨线重访是全局事实：线路重复数之和不能替代节期重复估计。
        route_rep = sum(expand(RESIDENTS, COVERED_STRATA, route=r, metric='rep')[0]
                        for r in ['R1', 'R2', 'R3'])
        fest_rep = expand(RESIDENTS, COVERED_STRATA, metric='rep')[0]
        self.assertAlmostEqual(route_rep, 0.0)
        self.assertGreater(fest_rep, 0)

    def test_repeat_is_distinct_occurrences(self):
        # 跨线重复者 17? 不，23 人是跨线；同点重复 6 人；节期重复 23。
        ans = [r for r in RESIDENTS if r['response'] == 'answered']
        rep = [r for r in ans if len(set(occs(r))) >= 2]
        self.assertEqual(len(rep), 23)
        self.assertTrue(all(len(set(occs(r))) == 2 for r in rep))
        # 每人的场次不重复列同一 occurrence
        for r in ans:
            self.assertEqual(len(occs(r)), len(set(occs(r))))


class Links(unittest.TestCase):
    def test_only_confirmed_same_is_merged(self):
        confirmed = link_additions()
        pending = link_additions(pending=True)
        self.assertEqual(confirmed, {'Q020': {'P3'}})
        self.assertIn('Q005', pending)
        # different 永不并入
        self.assertNotIn('Q003', confirmed)
        self.assertEqual(pending.get('Q003'), {'P4'} if 'Q003' in pending else None)

    def test_pending_links_do_not_change_repeat_count(self):
        base = expand(RESIDENTS, COVERED_STRATA, metric='rep')[0]
        alt = expand(RESIDENTS, COVERED_STRATA, metric='rep', extra=link_additions(pending=True))[0]
        self.assertEqual(base, alt)


class Uncertainty(unittest.TestCase):
    def test_publication_rule_30_percent(self):
        est, se, parts = expand(RESIDENTS, COVERED_STRATA, metric='any')
        t = tcrit(sum(p[3] for p in parts) - len(parts))
        self.assertLessEqual(2 * t * se / est, 0.30)
        est2, se2, parts2 = expand(RESIDENTS, COVERED_STRATA, metric='rep')
        t2 = tcrit(sum(p[3] for p in parts2) - len(parts2))
        self.assertGreater(2 * t2 * se2 / est2, 0.30)

    def test_unanswered_bounds_bracket_point(self):
        for metric in ('any', 'rep'):
            pt = expand(RESIDENTS, COVERED_STRATA, metric=metric)[0]
            lo = expand(RESIDENTS, COVERED_STRATA, metric=metric, mode='lower')[0]
            hi = expand(RESIDENTS, COVERED_STRATA, metric=metric, mode='upper')[0]
            self.assertLessEqual(lo, pt)
            self.assertGreaterEqual(hi, pt)
