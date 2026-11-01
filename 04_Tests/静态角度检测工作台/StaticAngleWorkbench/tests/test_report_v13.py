"""V1.3 Excel 实体生成和持久化备份回读测试。无需连接转台。"""
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from openpyxl import load_workbook
from app.core.calibration import Calibration
from app.core.report import export_report, save_checkpoint, export_from_checkpoint, checkpoint_path

ROOT = Path(__file__).resolve().parents[1]


def fake_rows():
    rows = []
    for channel, inner in [('Y', 0), ('X', 90)]:
        for signed in range(-180, 181, 10):
            i = len(rows)
            rows.append(dict(ok=True, channel=channel, inner_deg=inner,
                             outer_signed_deg=signed,
                             inner_actual=inner, outer_actual=signed % 360,
                             measured_deg=signed + 0.02,
                             reference_deg=signed, error_deg=0.02,
                             norm_g=1.0, accepted_frames=220, frames=224,
                             rejected_fraction=.025,
                             started_at='2026-10-23T10:01:01',
                             ended_at='2026-10-23T10:01:06',
                             raw=(0.001, -0.002, 0.999),
                             corrected=(0.0, 0.0, 1.0),
                             std_g=(.002, .002, .002)))
    return rows


class ReportExportV13Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal = Calibration.load(ROOT / 'examples/accel_calibration_example.json')

    def test_export_74_points(self):
        with TemporaryDirectory() as d:
            target = Path(d) / '静态角度检测结果_中文.xlsx'
            rows = fake_rows()
            output = export_report(target, rows, self.cal, {'转台串口':'COM2'}, '完成')
            self.assertEqual(output, target)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 7000)
            wb = load_workbook(output, read_only=False, data_only=True)
            self.assertEqual(wb.sheetnames, ['检测汇总', '逐点结果', '校准与参数'])
            summary, detail, params = wb.worksheets
            self.assertEqual(summary['B13'].value, 37)
            self.assertEqual(summary['B14'].value, 37)
            self.assertAlmostEqual(summary['D13'].value, .02, places=7)
            self.assertEqual(detail.max_row, 75)
            self.assertEqual(detail['B2'].value, 'Y')
            self.assertEqual(detail['D2'].value, -180.0)
            self.assertEqual(detail['E39'].value, 90)
            self.assertEqual(detail['B75'].value, 'X')
            self.assertEqual(detail['Y75'].value, .002)
            self.assertGreater(len(summary._charts), 0)
            self.assertIn('仅试运行', str(summary['B9'].value))
            self.assertIn('校正公式', [r[0] for r in params.values])
            wb.close()
            self.assertEqual(list(Path(d).glob('*.tmp')), [])

    def test_checkpoint_round_trip(self):
        with TemporaryDirectory() as d:
            target = Path(d) / '报告.xlsx'
            rows = fake_rows()[:6]
            checkpoint = save_checkpoint(target, rows, self.cal, {'采样时间秒':5.0}, '中止','人为终止')
            self.assertEqual(checkpoint, checkpoint_path(target))
            self.assertTrue(checkpoint.exists())
            restored = Path(d) / '从备份恢复.xlsx'
            export_from_checkpoint(checkpoint, restored)
            wb = load_workbook(restored)
            self.assertEqual(wb['逐点结果'].max_row, 7)
            self.assertEqual(wb['检测汇总']['B13'].value, 6)
            self.assertEqual(wb['检测汇总']['B14'].value, 0)
            self.assertEqual(wb['检测汇总']['B5'].value, '中止')
            self.assertEqual(wb['检测汇总']['B6'].value, '人为终止')
            wb.close()

    def test_does_not_corrupt_previous_file_on_export_error(self):
        with TemporaryDirectory() as d:
            target = Path(d)/'keep.xlsx'
            target.write_bytes(b'KEEP ORIGINAL')
            with mock.patch('app.core.report.os.replace', side_effect=PermissionError('目标 Excel 正被占用')):
                with self.assertRaisesRegex(PermissionError, '占用'):
                    export_report(target, fake_rows()[:1], self.cal, {'采样时间秒': 5}, '完成')
            self.assertEqual(target.read_bytes(), b'KEEP ORIGINAL')
            self.assertEqual(sorted(str(p) for p in Path(d).glob('.*.xlsx')), [])

    def test_no_artifact_tool_import(self):
        text = (ROOT/'app/core/report.py').read_text(encoding='utf-8')
        self.assertNotIn('from artifact_tool import', text)
        requirements = (ROOT/'requirements.txt').read_text()
        self.assertIn('openpyxl', requirements)
        self.assertNotIn('artifact-tool', requirements)


if __name__ == '__main__':
    unittest.main()
