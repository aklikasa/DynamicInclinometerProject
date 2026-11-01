import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.scan_plan import make_scan_plan

class PlanTests(unittest.TestCase):
    def test_scan_layout(self):
        pts = make_scan_plan()
        self.assertEqual(len(pts),74)
        self.assertEqual((pts[0].channel,pts[0].inner_deg,pts[0].outer_signed_deg,pts[0].outer_command_deg),('Y',0,-180,180))
        self.assertEqual((pts[37].channel,pts[37].inner_deg,pts[37].outer_signed_deg),('X',90,-180))
        self.assertEqual(pts[-1].outer_signed_deg,180)

if __name__=='__main__':unittest.main()
