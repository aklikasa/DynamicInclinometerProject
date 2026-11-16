# -*- coding: utf-8 -*-
"""无硬件自动Excel报告回归：python tools/test_calibration_excel_report.py"""
from pathlib import Path
import sys, tempfile, zipfile, math
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from calibration_excel_report import create_validation_workbook


def _acc(ref,step,split):
    r=[float(x) for x in ref]
    return {'step_id':step,'split':split,'inner_target_deg':60.,'outer_target_deg':90.,
            'gravity_reference_platform_g':r,'acc_raw_mean_g':[r[0]+0.01,r[1]-0.01,r[2]+0.02],
            'accepted_frames':220,'temperature_mean_c':24.9}


def _gyro(ref,step,split):
    r=[float(x) for x in ref]
    return {'step_id':step,'split':split,'axis':'inner','target_rate_dps':r[2],
            'reference':r,'measured':[r[0]+0.05,r[1]-0.03,r[2]+0.02],
            'accepted_frames':245,'temperature_mean_c':25.0}


def test():
    common={'run_id':'SYNTHETIC_TEST','device_serial':'DEMO_NOT_MEASURED',
            'quality_gate':{'verdict':'PILOT_PASS_NOT_RELEASED','metric_pass':True,
                            'gates':{'test_limit':{'value':0.05,'limit':0.10,'pass':True}}}}
    ident=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]
    a={**common,'raw_accel_bias_g':[0.,0.,0.], 'raw_to_platform_matrix':ident,
       'position_measurements':[_acc([0,0,1],'F1','fit'),_acc([0.5,0.5,math.sqrt(.5)],'V1','validate')]}
    g={**common,'raw_gyro_bias_dps':[0.,0.,0.], 'raw_to_platform_matrix':ident,
       'fit_measurements':[_gyro([0,0,1],'F1','fit')],
       'validation_measurements':[_gyro([0,0,2],'V1','validate'),_gyro([0,0,0],'ZERO','validate')]}
    alignment={**common,'combined_calibration':{'accelerometer':{'raw_bias_g':[0,0,0],'raw_to_platform_matrix':ident},
                   'gyroscope':{'raw_bias_dps':[0,0,0],'raw_to_platform_matrix':ident}},
            'validation_measurements':{'acc':[_acc([0,0,1],'A','validate')],
                                       'gyro':[_gyro([0,0,0],'G','validate')]}}
    with tempfile.TemporaryDirectory() as d:
        for kind,result,count in [('accel',a,3),('gyro',g,3),('align',alignment,4)]:
            filename=create_validation_workbook(kind,result,d)
            assert Path(filename).is_file(),filename
            with zipfile.ZipFile(filename) as z:
                assert z.testzip() is None
                root=ET.fromstring(z.read('xl/workbook.xml'))
                sheets=root.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet')
                assert len(sheets)==count,(kind,len(sheets))
                for i in range(1,count+1):
                    content = z.read(f'xl/worksheets/sheet{i}.xml')
                    sheet = ET.fromstring(content)
                    assert len(sheet.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')) >= 4
                    assert len(sheet.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c')) >= 12
    print('PASS: ACC/GYRO/六轴多工作表XLSX生成、XML和压缩包完整性检查')

if __name__=='__main__':test()
