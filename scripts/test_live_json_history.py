import io
import json
import unittest
from unittest.mock import Mock, patch

from compare_live_json_timestamps import fetch_block


class HistoryTests(unittest.TestCase):
    def test_moved_accession_keeps_actual_source_url(self):
        root={'filings':{'recent':{'accessionNumber':['a'],'acceptanceDateTime':['2025-01-01T12:00:00Z']},
                         'files':[{'name':'CIK0000000001-submissions-001.json'}]}}
        history={'accessionNumber':['b'],'acceptanceDateTime':['2024-01-01T12:00:00Z']}
        responses=[io.BytesIO(json.dumps(x).encode()) for x in (root,history)]
        with patch('compare_live_json_timestamps.urllib.request.urlopen',side_effect=responses):
            matched,report=fetch_block(('CIK0000000001.json',[(1,'a','raw-a'),(1,'b','raw-b')]),Mock(),True)
        self.assertEqual(report[1:],(2,0,None))
        self.assertTrue(matched[1][4].endswith('CIK0000000001-submissions-001.json'))

    def test_history_failure_preserves_recent_matches(self):
        root={'filings':{'recent':{'accessionNumber':['a'],'acceptanceDateTime':['2025-01-01T12:00:00Z']},
                         'files':[{'name':'CIK0000000001-submissions-001.json'}]}}
        with patch('compare_live_json_timestamps.urllib.request.urlopen',
                   side_effect=[io.BytesIO(json.dumps(root).encode()),TimeoutError('test')]):
            matched,report=fetch_block(('CIK0000000001.json',[(1,'a','raw-a'),(1,'b','raw-b')]),Mock(),True)
        self.assertEqual(len(matched),1)
        self.assertEqual(report[1:3],(1,1))
        self.assertIsNotNone(report[3])


if __name__=='__main__':
    unittest.main()
