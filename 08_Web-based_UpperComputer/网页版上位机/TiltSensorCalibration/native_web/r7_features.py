# -*- coding: utf-8 -*-
"""R7 research preparation and completed-run analysis. No actuator writes.

The experiment DRAFT is not an auto-run checkpoint and must never be mistaken
for a safe control plan. R7 Qt state-machine has not been ported to Web yet.
"""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
import re
import threading

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'native_web_data'
IMPORTED_RUNS = DATA / 'imported_R7_experiments'
IMPORTED_RUNS.mkdir(parents=True, exist_ok=True)
DRAFT = DATA / 'r7_web_draft.json'
_DEFAULT = {
    'sn': '', 'fit_temperatures': '20, 25, 30, 35, 40',
    'validation_temperatures': '22.5, 27.5, 32.5, 37.5',
    'production_mode':'legacy', 'curve_policy':'single', 'batch_id':'',
    'quality_mode': 'production_adaptive', 'chamber_mode': 'plc',
    'gyro_fit_rates':'1, 2, 3, 5, 10, 20, 30',
    'gyro_verify_rates':'1.5, 2.5, 4, 7.5, 15, 25',
    'expected_gyro_fs':250, 'dwell_seconds':300,
    'max_quality_holds':5, 'max_stabilization_wait_minutes':120,
    'recovery_wait_minutes':45, 'pv_initial_band_c':1.0, 'pv_soak_band_c':1.0,
    'wk_std_low':0.180, 'wk_std_high':0.240,
}


def _read_json(path, limit=30_000_000):
    if path.stat().st_size > limit:
        raise ValueError('实验文件超过大小限制，拒绝直接读取')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_draft(body):
    """Use R7's *actual* temperature/rate validators, not homemade shortcuts."""
    from thermal_variable_temperature import separate_temperature_plan
    from thermal_gyro_multirate import parse_rate_list, validate_rate_lists
    if not isinstance(body, dict):
        raise ValueError('方案必须是 JSON 对象')
    if any(k not in _DEFAULT for k in body):
        raise ValueError('方案包含未知字段')
    d = dict(_DEFAULT, **body)
    for key in ('sn','batch_id'):
        if not isinstance(d[key], str) or len(d[key]) > 80 or not re.fullmatch(r'[\w\-\.\u4e00-\u9fff]*', d[key]):
            raise ValueError(key + ' 格式不合法')
    for key, choices in [('production_mode', ('legacy','combined','warming','cooling')),
                         ('curve_policy', ('single','research_directional')),
                         ('quality_mode', ('continuous','production_adaptive','strict')),
                         ('chamber_mode', ('plc','manual'))]:
        if d[key] not in choices:
            raise ValueError(key+' 无效')
    for key, lo, hi in [('dwell_seconds',300,7200), ('max_quality_holds',1,100),
                         ('max_stabilization_wait_minutes',1,1440),
                         ('recovery_wait_minutes',1,1440)]:
        v=d[key]
        if type(v) is not int or not lo<=v<=hi:
            raise ValueError(f'{key} 必须是 {lo}–{hi} 整数')
    if d['expected_gyro_fs'] not in (125,250,500,1000,2000,4000):
        raise ValueError('GYRO 预期量程不合法')
    for key,lo,hi in [('pv_initial_band_c',.1,5.),('pv_soak_band_c',.1,5.),
                      ('wk_std_low',.08,.35),('wk_std_high',.1,.6)]:
        v=d[key]
        if type(v) not in (int,float) or not lo<=v<=hi:
            raise ValueError(f'{key} 超出原 R7 允许范围 {lo}–{hi}')
    fit=parse_rate_list(d['gyro_fit_rates'],'拟合速率')
    verify=parse_rate_list(d['gyro_verify_rates'],'验证速率')
    fit,verify=validate_rate_lists(fit,verify)
    plan=separate_temperature_plan(d['fit_temperatures'], d['validation_temperatures'])
    return d, {'fit_temperatures':plan['fit_temperatures_c'],
               'validation_temperatures':plan['validation_temperatures_c'],
               'execution_order':plan['temperature_setpoints_c'],
               'temperature_split':{str(k):v for k,v in plan['temperature_split'].items()},
               'gyro_fit_rates':list(fit), 'gyro_verify_rates':list(verify),
               'r7_policy': {
                   'target_sp_direct':True,
                   'cross_pose_chip_span_is_rejection':False,
                   'fit_strategy':'12姿态完整联合拟合（production_adaptive 时）',
                   'per_condition_die_temperature':True,
                   'actuator_commands_enabled':False,
               },
               'notice':'仅验证并保存实验草稿，不会开始温补、移动 WK 或写 PLC SP。'}


class R7Workspace:
    def __init__(self):
        self.lock=threading.RLock()
        self.job={'state':'idle','message':'尚未运行离线分析','run':''}

    def draft(self):
        try:
            d=_read_json(DRAFT,32_000)
            return {**_DEFAULT, **{k:v for k,v in d.items() if k in _DEFAULT}}
        except (OSError,ValueError,TypeError):
            return dict(_DEFAULT)

    def save_draft(self,body):
        d,plan=validate_draft(body)
        tmp=DRAFT.with_suffix('.tmp')
        tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(DRAFT)
        return {'draft':d,'preview':plan}

    def preview(self,body):
        _,plan=validate_draft(body)
        return plan

    def poses(self):
        # R7 source of truth. Loading this module runs no motor command.
        from production_calibration import acc_fit_steps, acc_verify_steps
        return {'fit':acc_fit_steps(), 'verify':acc_verify_steps()}

    def _run_path(self,run):
        if not isinstance(run,str) or not re.fullmatch(r'[\w\-.\u4e00-\u9fff ]{1,120}',run):
            raise ValueError('实验目录名称无效')
        directory=(IMPORTED_RUNS/run).resolve()
        if directory.parent!=IMPORTED_RUNS.resolve() or not directory.is_dir():
            raise FileNotFoundError('实验目录不存在，请先将原 R7 完整实验文件夹复制到 imported_R7_experiments')
        return directory

    def list_runs(self):
        runs=[]
        for p in sorted(IMPORTED_RUNS.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
            if not p.is_dir() or p.is_symlink() or len(runs)>=80:continue
            config=p/'experiment_config.json';checkpoint=p/'temperature_measurements.json'
            if not(config.is_file() and checkpoint.is_file()):continue
            try:
                state=_read_json(checkpoint).get('status','未知')
                details=_read_json(config,128_000)
                runs.append({'name':p.name,'status':state, 'quality_mode':details.get('temperature_quality_mode','旧版/未知'),
                             'device_sn':details.get('device_sn',''), 'updated':datetime.fromtimestamp(checkpoint.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
                             'has_results':(p/'thermal_model_selection.json').exists()})
            except (OSError,ValueError,TypeError,KeyError):continue
        return runs

    def detail(self,name):
        p=self._run_path(name)
        config=_read_json(p/'experiment_config.json',128_000)
        checkpoint=_read_json(p/'temperature_measurements.json')
        rows=checkpoint.get('rows',[])
        if not isinstance(rows,list):raise ValueError('保存的逐工况记录格式无效')
        # Include R7's independent ACC/GYRO reports inside subfolders too.
        # Never expose symlinks outside the explicitly imported experiment root.
        files=[]
        for f in sorted(p.rglob('*')):
            if len(files)>=200:break
            rel=f.relative_to(p)
            if len(rel.parts)>3 or not f.is_file() or f.is_symlink():continue
            if not f.resolve().is_relative_to(p) or f.suffix.lower() not in ('.xlsx','.json','.md','.html'):continue
            if f.stat().st_size>=50_000_000:continue
            files.append({'name':rel.as_posix(),'bytes':f.stat().st_size})
        return {'name':name, 'status':checkpoint.get('status'), 'rows':len(rows),
                'config':{'quality_mode':config.get('temperature_quality_mode'),
                          'device_sn':config.get('device_sn'),
                          'temperatures':config.get('temperature_setpoints_c')},
                'files':files[:200]}

    def file(self,run,filename):
        p=self._run_path(run)
        if not isinstance(filename,str) or len(filename)>230 or '\\' in filename:
            raise ValueError('文件路径无效')
        relative=Path(filename)
        if relative.is_absolute() or '..' in relative.parts or len(relative.parts)>3:
            raise ValueError('不允许越级访问')
        f=(p/relative).resolve()
        if not f.is_relative_to(p) or not f.is_file() or f.stat().st_size>50_000_000:
            raise FileNotFoundError('报告不存在')
        if f.suffix.lower() not in ('.xlsx','.json','.md','.html'):
            raise ValueError('不允许下载该文件类型')
        return f

    def analyze(self,name,can_run=True):
        if not can_run:raise ValueError('PCB 正在记录数据，先停止录制再执行离线分析')
        p=self._run_path(name)
        with self.lock:
            if self.job['state']=='running':raise ValueError('已有一项离线分析正在执行')
            cp=_read_json(p/'temperature_measurements.json')
            cfg=_read_json(p/'experiment_config.json',128_000)
            if cp.get('status') not in ('COMPLETED','PARTIAL_COMPLETED'):
                raise ValueError('只有 COMPLETED / PARTIAL_COMPLETED 实验允许离线模型复算')
            if not isinstance(cp.get('rows'),list) or not cp['rows']:
                raise ValueError('实验没有已接受的有效工况')
            if not isinstance(cfg.get('temperature_setpoints_c'),list):
                raise ValueError('原实验缺少温度设定点')
            self.job={'state':'running','message':'正在使用 R7 原版算法校验完整工况、复算模型与生成 Excel','run':name}
            threading.Thread(target=self._worker,args=(p,),daemon=True,name='R7-offline-model').start()
        return dict(self.job)

    def _worker(self,p):
        try:
            from thermal_model_completion import fully_accepted_sensors
            from thermal_analysis_publisher import publish_sensor_reports
            checkpoint=_read_json(p/'temperature_measurements.json')
            config=_read_json(p/'experiment_config.json',128_000)
            sensors=fully_accepted_sensors(config,checkpoint)
            if not sensors:raise ValueError('ACC/GYRO 工况不完整，不会生成虚假的28模型结果')
            output=p/('模型优选离线复算_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
            output.mkdir(exist_ok=False)
            result=publish_sensor_reports(output,checkpoint['rows'],
                      [float(v) for v in config['temperature_setpoints_c']],
                      sensors,source_folder=p)
            select=result.get('selection',{}).get('sensors',{})
            summary='；'.join(f'{s.upper()}: {v.get("selected_id") or "未选出"} / {v.get("status")}' for s,v in select.items())
            with self.lock:self.job={'state':'complete','message':summary or '研发报告已经生成','run':p.name,'output':output.name}
        except Exception as exc:
            with self.lock:self.job={'state':'error','message':f'{type(exc).__name__}: {str(exc)[:400]}','run':p.name}

    def job_state(self):
        with self.lock:return dict(self.job)
