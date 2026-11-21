from collections import defaultdict
import unittest

from inspect_inputs import read_tables


class SourceRecords(unittest.TestCase):
    def test_drawn_families_match_frames(self):
        tables = read_tables()
        families = defaultdict(set)
        for row in tables['residents']:
            families[row['stratum']].add(row['household'])
        for row in tables['frame']:
            self.assertEqual(len(families[row['stratum']]), int(row['drawn']))
            self.assertLessEqual(int(row['covered']), int(row['eligible']))

    def test_candidates_and_accepted_fieldwork(self):
        tables = read_tables()
        forms = {row['form'] for row in tables['audits']}
        persons = {row['record'] for row in tables['residents']}
        for row in tables['links']:
            self.assertIn(row['form'], forms)
            self.assertIn(row['record'], persons)
        self.assertLess(len({(row['form'],row['record']) for row in tables['links']}),len(tables['links']))
        assignments = [row for row in tables['follow_up'] if row['day']=='D3']
        self.assertEqual(1, sum(row['state']=='accepted' for row in assignments))
        self.assertTrue(set(assignments[0]['links'].split('+')) & set(assignments[1]['links'].split('+')))

    def test_supplement_preserves_roster_and_return_types(self):
        tables = read_tables()
        roster = {row['household']:row for row in tables['roster']}
        shifts = {row['shift']:row for row in tables['follow_up']}
        links = {row['link'] for row in tables['links']}
        for row in tables['returns']:
            self.assertIn(row['shift'],shifts)
            refs = roster if row['phase']=='random' else links
            self.assertIn(row['target'],refs)
        self.assertTrue(any(row['action']=='route_closed' for row in tables['availability']))
        self.assertEqual(1,len({row['frame_frozen'] for row in roster.values()}))
