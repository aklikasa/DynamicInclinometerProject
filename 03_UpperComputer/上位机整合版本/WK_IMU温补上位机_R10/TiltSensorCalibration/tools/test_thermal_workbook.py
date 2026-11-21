# -*- coding: utf-8 -*-
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thermal_excel_report import export_thermal_xlsx
from openpyxl import load_workbook
with tempfile.TemporaryDirectory() as d:
    r={'temperature_target_c':25,'temperature_split':'fit','step_id':'TEST',
       'sensor':'acc','mode':'static','split':'fit','temperature_mean_c':25,
       'inner_actual_mean_deg':0,'outer_actual_mean_deg':0,
       'inner_rate_mean_dps':0,'outer_rate_mean_dps':0,
       'reference':[0,0,1],'acc_raw_mean_g':[0.01,-0.02,1.01],
       'accepted_frames':54,'frame_count':58}
    name=export_thermal_xlsx(d,[r],{'sensors':{'acc':{'status':'candidate_created',
                                        'temperature_holdout':{'vector_rmse':0.001,'unit':'g'}}}})
    book=load_workbook(name,read_only=True)
    assert all(x in book.sheetnames for x in ('温补总览','逐工况测量','GYRO速率覆盖及缺失概览'))
    assert book['逐工况测量']['N2'].value==1
    assert book['温补总览']['B3'].value=='candidate_created'
    print('PASS: 温补 Excel 生成、工作表与逐工况数据核对')
