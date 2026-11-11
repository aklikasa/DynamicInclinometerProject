# -*- coding: utf-8 -*-
"""R7 Qt-free, operator-guided ambient ACC/GYRO acquisition and model comparison.

This module NEVER issues motor commands. A physical operator positions/starts and
stops the 2TD600 using the existing separate control interface. Captures use the
single PCB polling thread's telemetry callback, with contemporaneous turntable
feedback; no second COM handle, sensor simulation or fabricated samples.

A complete autonomous motion sequencer is deliberately NOT provided here.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

import numpy as np
from production_calibration import (
    load_profile, acc_fit_steps, acc_verify_steps, gyro_fit_steps, gyro_verify_steps,
    verify_sensor_config, sensor_config_consistent, frame_average_sanitized,
    robust_segment,
)
from calibration_model_compare import compare_models, serialize
from model_comparison_report import save_model_comparison

BASE = Path(__file__).resolve().parent.parent / 'native_web_data' / 'ambient_guided_runs'
BASE.mkdir(parents=True, exist_ok=True)
AXIS_MODEL = 'outer_x_inner_z'


def _utc():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds')


def _rot_x(deg):
    t=math.radians(deg);c,s=math.cos(t),math.sin(t)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]],dtype=float)


def _rot_z(deg):
    t=math.radians(deg);c,s=math.cos(t),math.sin(t)
    return np.array([[c,-s,0],[s,c,0],[0,0,1]],dtype=float)


def _gravity(inner, outer, sign):
    return (_rot_x(outer) @ _rot_z(inner)).T @ np.array([0,0,sign],dtype=float)


def _omega(inner, outer, inner_dps, outer_dps):
    outer_rot = _rot_x(outer)
    whole = outer_rot @ _rot_z(inner)
    base = outer_dps*np.array([1.,0,0]) + inner_dps*(outer_rot@np.array([0.,0,1]))
    return whole.T @ base


def _difference(a,b):
    return (float(a)-float(b)+180)%360-180


class AmbientGuided:
    def __init__(self, service, directory=BASE, clock=time.monotonic):
        self.service=service
        self.base=Path(directory)
        self.base.mkdir(parents=True,exist_ok=True)
        self.clock=clock
        self.lock=threading.RLock()
        self.session=None
        self.capture=None
        self.last_error=''

    def is_collecting(self):
        with self.lock:
            return bool(self.session and self.session['state']=='collecting')

    def _write(self, name, content):
        if not self.session:
            return
        target=self.base/self.session['run_id']/name
        target.parent.mkdir(exist_ok=True)
        temporary=target.with_suffix(target.suffix+'.tmp')
        temporary.write_text(json.dumps(serialize(content),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.replace(target)

    def _audit(self,event,message):
        if not self.session:
            return
        record={'utc':_utc(),'event':event,'message':str(message)[:750]}
        with (self.base/self.session['run_id']/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(record,ensure_ascii=False)+'\n')
        self.last_error=record['message'] if event in ('ERROR','REJECT') else ''

    def _store(self):
        if self.session:
            values={k:v for k,v in self.session.items() if k not in ('profile','steps')}
            values['profile']=self.session['profile']
            values['steps']=self.session['steps']
            self._write('session.json',values)

    def _live(self):
        state=self.service.status()
        if not (state['imu']['reading'] and state['td']['reading']):
            raise RuntimeError('真实 PCB 或 2TD600 无新鲜反馈；请先连接两台设备')
        if state['imu']['recording']:
            raise RuntimeError('原始 CSV 正在记录，先停止手工记录，避免混合实验')
        return state

    def _sensor(self,profile):
        imu=self.service.imu_mod
        if imu is None:
            raise RuntimeError('PCB 未连接')
        d=imu.tiltSensorRawData
        with d.data_lock:
            raw={k:getattr(d,k) for k in ('acc_fs','gyro_fs','acc_fs_ever_valid','gyro_fs_ever_valid','data_odr')}
        return verify_sensor_config(profile,raw)

    def _safety(self):
        # An encoder angle is not sufficient. Read the original DLL's interlocks.
        with self.service.td_io_lock:
            return self.service._td_safety_snapshot()

    def _check_step_feedback(self,step,state):
        td=state['td']
        if td.get('feedback_age_ms') is None or td['feedback_age_ms']>750:
            raise RuntimeError('转台反馈延迟过大；不能保证与 IMU 同步')
        if td['motion'].get('state') in ('moving','stopping','fault'):
            raise RuntimeError('手动位置运动尚未确认完成；请等待转台状态稳定')
        axes=self._safety()
        for name in ('inner','outer'):
            # While acquiring a continuous-rate condition, the rotating axis
            # cannot remain at its initial pose. Only its partner must hold.
            if step['mode']=='rate' and name==step['rotation_axis']:
                continue
            if abs(_difference(axes[name]['position'],step[name+'_deg']))>0.2:
                raise RuntimeError(f'{name} 轴反馈角度未到目标 {step[name+"_deg"]}°，当前 {axes[name]["position"]:.3f}°')
        if step['mode']=='static':
            if any(abs(s['speed'])>0.05 for s in axes.values()):
                raise RuntimeError('静态采样前两轴角速度必须均低于 0.05°/s')
        else:
            axis=step['rotation_axis'];target=float(step['target_rate_dps'])
            other='inner' if axis=='outer' else 'outer'
            tolerance=max(0.2,abs(target)*0.15)
            if abs(axes[axis]['speed']-target)>tolerance:
                raise RuntimeError(f'当前 {axis} 轴速度 {axes[axis]["speed"]:.3f}°/s，未稳定到 {target}°/s')
            if abs(axes[other]['speed'])>0.05:
                raise RuntimeError('另一轴必须保持静止，不能双轴同时匀速采样')
        return axes

    def start(self, request):
        if not isinstance(request,dict): raise ValueError('数据格式错误')
        kind=request.get('kind')
        if kind not in ('acc','gyro'): raise ValueError('只能选择 ACC 或 GYRO')
        sn=request.get('device_serial','')
        if not isinstance(sn,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}',sn):
            raise ValueError('请输入有效的 1～64 位 PCB 唯一编号')
        gravity=request.get('gravity_sign',1)
        if type(gravity) is not int or gravity not in (-1,1):
            raise ValueError('重力参考符号必须为 +1 或 -1')
        if request.get('safety_ack')!='PHYSICAL_ESTOP_READY':
            raise ValueError('必须现场确认转台安装、线缆、硬件急停及工艺轴系后才能创建采样会话')
        with self.lock:
            if self.session and self.session['state'] in ('ready','collecting','analyzing'):
                raise RuntimeError('已有未完成的常温标定会话，请先完成或取消')
            st=self._live()
            self._safety()
            p=load_profile(str(Path(__file__).resolve().parent.parent))
            sensor=self._sensor(p)
            steps=(acc_fit_steps()+acc_verify_steps() if kind=='acc' else
                   gyro_fit_steps(p)+gyro_verify_steps(p))
            if any(abs(float(x.get('target_rate_dps',0)))>float(p['rates']['maximum_command_rate_dps']) for x in steps):
                raise RuntimeError('工艺速率超过 R7 软件限速')
            run_id='GUIDED_'+kind.upper()+'_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:6]
            (self.base/run_id).mkdir()
            self.session={'run_id':run_id,'kind':kind,'device_serial':sn,'gravity_sign':gravity,
                          'axis_model':AXIS_MODEL,'sensor_configuration':sensor,'profile':p,'steps':steps,
                          'state':'ready','index':0,'accepted':[],'rejections':[],
                          'started_at':_utc(),'updated_at':_utc(), 'production_release_allowed':False,
                          'acquisition_mode':'OPERATOR_GUIDED_REAL_HARDWARE_NOT_AUTONOMOUS'}
            self.capture=None
            self.last_error=''
            self._audit('START',f'创建 {kind} 工况 {len(steps)} 步；不发送转台运动命令')
            self._store()
            return self.status()

    def status(self):
        with self.lock:
            if not self.session:
                return {'state':'idle','automatic_motion':False,'notice':'未创建引导采样会话'}
            s=self.session
            step=s['steps'][s['index']] if s['index']<len(s['steps']) else None
            cap=self.capture
            return {'state':s['state'],'automatic_motion':False,'run_id':s['run_id'],'kind':s['kind'],
                    'index':s['index'],'total':len(s['steps']),'current_step':step,
                    'accepted':len(s['accepted']),'rejected':len(s['rejections']),
                    'sample_count':len(cap['frames']) if cap else 0,
                    'elapsed_seconds':round(self.clock()-cap['started_monotonic'],1) if cap else None,
                    'required_seconds':cap['seconds'] if cap else (step.get('sample_seconds',s['profile']['timing']['static_seconds' if step['mode']=='static' else 'rate_seconds']) if step else None),
                    'last_error':self.last_error,
                    'model_report_ready':bool(s.get('report_ready')),
                    'notice':'操作员逐工况采样；不自动向转台发送位置、速率或找零指令；生产放行禁止'}

    def begin(self,body=None):
        with self.lock:
            if not self.session or self.session['state']!='ready':
                raise RuntimeError('当前没有等待采样的工况')
            s=self.session
            step=s['steps'][s['index']]
            state=self._live()
            self._check_step_feedback(step,state)
            current=self._sensor(s['profile'])
            if not sensor_config_consistent(s['sensor_configuration'],current):
                raise RuntimeError('PCB 量程或 ODR 与会话开始时不一致，禁止混用数据')
            seconds=float(step.get('sample_seconds',s['profile']['timing']['static_seconds' if step['mode']=='static' else 'rate_seconds']))
            self.capture={'step_id':step['step_id'],'started_monotonic':self.clock(),
                          'seconds':seconds,'frames':[],'td_polls':[], 'dropped_stale':0,'dropped_invalid':0}
            s['state']='collecting'
            s['updated_at']=_utc()
            self._audit('CAPTURE_BEGIN',step['step_id'])
            self._store()
            return self.status()

    def on_turntable_poll(self,axes,monotonic):
        """True independent encoder polls: one observation per actual DLL poll.

        Unlike per-IMU-frame cached rates, duplicate cached feedback cannot be
        treated as statistically independent evidence of stable angular speed.
        """
        with self.lock:
            if self.capture and self.session and self.session['state']=='collecting':
                cap=self.capture
                if monotonic-cap['started_monotonic']<=cap['seconds'] and len(cap['td_polls'])<1000:
                    cap['td_polls'].append({'t':float(monotonic),
                        'inner_deg':float(axes['inner']['angle']),
                        'outer_deg':float(axes['outer']['angle']),
                        'inner_speed':float(axes['inner']['speed']),
                        'outer_speed':float(axes['outer']['speed'])})

    @staticmethod
    def _rate_diagnostic(polls,axis,target):
        import numpy as np
        # Encoder position difference per independent DLL poll. No copied IMU frames.
        if len(polls)<12:raise ValueError('独立转台角度反馈不足 12 次，拒绝速率标定')
        samples=[]
        for prev,curr in zip(polls,polls[1:]):
            dt=float(curr['t'])-float(prev['t'])
            if not .025<=dt<=.75:continue
            delta=(float(curr[axis+'_deg'])-float(prev[axis+'_deg'])+180)%360-180
            samples.append(delta/dt)
        if len(samples)<10:raise ValueError('独立差分测速有效样本不足')
        arr=np.asarray(samples,float)
        mean=float(np.mean(arr));std=float(np.std(arr))
        return {'certified':bool(math.isfinite(mean) and math.isfinite(std)),
            'mean_dps':mean,'raw_diff_std_dps':std,'independent_samples':len(samples),
            'target_dps':float(target),'method':'independent_2TD600_encoder_poll_position_differences'}

    def on_frame(self,wall,raw):
        # Called on the original PCB poll thread, after one *valid* frame.
        # Keep work bounded: copy raw 16-point arrays, defer all NumPy work to HTTP.
        with self.lock:
            if not self.capture or not self.session or self.session['state']!='collecting':
                return
            cap=self.capture
            if len(cap['frames'])>=12000:
                cap['dropped_invalid']+=1;return
            mono=self.clock()
            if mono-cap['started_monotonic']>cap['seconds']:
                return  # Fixed acquisition window; late operator click adds no extra samples.
            with self.service.lock:
                td=dict(self.service.td_state)
                connected=self.service.td_connected
            age_ms=abs(mono-float(td.get('last_monotonic') or 0))*1000
            max_age=float(self.session['profile']['quality']['feedback_age_max_ms'])
            if not connected or age_ms>max_age or not td.get('inner') or not td.get('outer'):
                cap['dropped_stale']+=1;return
            with raw.data_lock:
                if not getattr(raw,'is_data_valid',False):
                    cap['dropped_invalid']+=1;return
                row={'acc_raw':[list(map(float,x)) for x in raw.acc_g_arr],
                     'gyro_raw':[list(map(float,x)) for x in raw.gyr_dps_arr],
                     'temp_c':float(raw.temp_c),'acc_fs':int(raw.acc_fs),
                     'gyro_fs':int(raw.gyro_fs),'data_odr':int(raw.data_odr),
                     'acc_fs_ever_valid':bool(raw.acc_fs_ever_valid),
                     'gyro_fs_ever_valid':bool(raw.gyro_fs_ever_valid),
                     'frame_update_count':int(raw.data_update_count)}
            row.update(inner_deg=float(td['inner']['angle']),outer_deg=float(td['outer']['angle']),
                       inner_rate_dps=float(td['inner']['speed']),outer_rate_dps=float(td['outer']['speed']),
                       feedback_delta_ms=age_ms,t=round(float(wall),4))
            cap['frames'].append(row)

    def finish(self,body=None):
        with self.lock:
            if not self.session or self.session['state']!='collecting' or not self.capture:
                raise RuntimeError('没有正在进行的采样')
            s=self.session;cap=self.capture;step=s['steps'][s['index']]
            elapsed=self.clock()-cap['started_monotonic']
            if elapsed+1e-9 < cap['seconds']:
                raise ValueError(f'采样时间不足，还需 {cap["seconds"]-elapsed:.1f} 秒')
            # End collection before CPU-intensive robust quality processing.
            self.capture=None
            s['state']='ready'
            rows=list(cap['frames'])
            try:
                self._live()
                self._check_step_feedback(step,self.service.status())
                current=self._sensor(s['profile'])
                if not sensor_config_consistent(s['sensor_configuration'],current):
                    raise ValueError('采样期间量程/ODR发生变化')
                converted=[]
                quality=s['profile']['quality']
                # Never accept a static window that wandered off the commanded
                # pose and returned. The R7 Qt timer checks this throughout.
                if step['mode']=='static':
                    for raw_row in rows:
                        if any(abs(_difference(raw_row[name+'_deg'],step[name+'_deg']))>0.2
                               for name in ('inner','outer')):
                            raise ValueError('静态采集过程中实际姿态偏离目标 0.2°')
                for row in rows:
                    acc,ca,va=frame_average_sanitized(row['acc_raw'],quality['mad_sigma'],True)
                    gyro,cg,vg=frame_average_sanitized(row['gyro_raw'],quality.get('gyro_mad_sigma',quality['mad_sigma']),True)
                    if acc is None or (s['kind']=='gyro' and gyro is None):continue
                    actual=verify_sensor_config(s['profile'],row)
                    if not sensor_config_consistent(s['sensor_configuration'],actual):
                        raise ValueError('工况采集过程中 PCB 量程/ODR 出现变化')
                    converted.append(dict(acc=acc.tolist(),gyro=gyro.tolist() if gyro is not None else [float('nan')]*3,
                        inner_deg=row['inner_deg'],outer_deg=row['outer_deg'],
                        inner_rate_dps=row['inner_rate_dps'],outer_rate_dps=row['outer_rate_dps'],temp_c=row['temp_c'],
                        feedback_delta_ms=row['feedback_delta_ms']))
                static_sensor='acc' if s['kind']=='acc' else 'gyro'
                reference=(self._rate_diagnostic(cap['td_polls'],step['rotation_axis'],step['target_rate_dps'])
                           if step['mode']=='rate' else None)
                stats=robust_segment(converted,step['mode'],s['profile'],
                                     static_sensor=static_sensor,
                                     target_rate=step.get('target_rate_dps'),axis=step.get('rotation_axis'),
                                     reference_diagnostic=reference)
                if step['mode']=='static':
                    ref=_gravity(stats['inner_actual_mean_deg'],stats['outer_actual_mean_deg'],s['gravity_sign']) if s['kind']=='acc' else np.zeros(3)
                    measured=stats['acc_raw_mean_g'] if s['kind']=='acc' else stats['gyro_raw_mean_dps']
                else:
                    ref=_omega(stats['inner_actual_mean_deg'],stats['outer_actual_mean_deg'],
                               stats['inner_rate_mean_dps'],stats['outer_rate_mean_dps'])
                    measured=stats['gyro_raw_mean_dps']
                accepted={'step_id':step['step_id'],'split':step['split'],
                          'mode':step['mode'],'reference':np.asarray(ref,float).tolist(),
                          'measured':list(map(float,measured)),
                          'target_inner_deg':step['inner_deg'],'target_outer_deg':step['outer_deg'],
                          'temperature_mean_c':stats['temperature_mean_c'],
                          'accepted_frames':stats['accepted_frames'],'total_frames':stats['frame_count'],
                          'feedback_dropped':cap['dropped_stale'], 'statistics':stats}
                s['accepted'].append(accepted)
                s['index']+=1
                s['updated_at']=_utc()
                self._audit('ACCEPT',f'{step["step_id"]}: {stats["accepted_frames"]} valid frames')
                self._write('measurements.json',s['accepted'])
                if s['index']==len(s['steps']):
                    s['state']='analyzing'
                    self._analyze()
                else:
                    self._store()
                return self.status()
            except (ValueError,TypeError,KeyError,RuntimeError) as exc:
                s['rejections'].append({'step_id':step['step_id'],'utc':_utc(),'reason':str(exc),
                                        'sampled_frames':len(rows),'dropped_stale':cap['dropped_stale']})
                s['updated_at']=_utc()
                self._audit('REJECT',f'{step["step_id"]}: {exc}')
                self._store()
                return self.status()

    def _analyze(self):
        s=self.session
        fit=[x for x in s['accepted'] if x['split']=='fit']
        val=[x for x in s['accepted'] if x['split']=='validate']
        try:
            if len(s['accepted']) != len(s['steps']) or len({x['step_id'] for x in s['accepted']}) != len(s['steps']):
                raise ValueError('采集不完整或步骤重复，禁止计算标定模型')
            result=compare_models(s['kind'],fit,val,s['profile'])
            result.update({'run_id':s['run_id'],'device_serial':s['device_serial'],
                           'schema_version':1,'axis_model':AXIS_MODEL,
                           'data_origin':'single R7 physical serial acquisition + 2TD600 measured encoder feedback',
                           'acquisition_mode':s.get('acquisition_mode','OPERATOR_GUIDED'), 'approved_for_production':False,
                           'production_release':'PROHIBITED: field commissioning and uncertainty verification not complete',
                           'sensor_configuration':s['sensor_configuration'],
                           'profile_snapshot':s['profile']})
            output=save_model_comparison(self.base/s['run_id'],s['kind'],result)
            s['model_report_files']=[Path(x).name for x in output]
            s['report_ready']=True
            s['state']='complete'
            self._audit('REPORT','A/B/C comparison and independent verification completed; no MCU writes')
        except Exception as exc:
            s['state']='analysis_failed'
            self._audit('ERROR','模型拟合或写报告失败: '+str(exc))
        finally:
            s['updated_at']=_utc()
            self._store()

    def cancel(self,body=None):
        with self.lock:
            if not self.session or self.session['state'] not in ('ready','collecting'):
                raise RuntimeError('没有需要取消的采样会话')
            self.capture=None
            self.session['state']='cancelled'
            self.session['updated_at']=_utc()
            self._audit('CANCEL','操作员取消引导采样；未发送任何转台动作或停车指令')
            self._store()
            return self.status()

    def list_reports(self):
        with self.lock:
            return [{'name':p.name,'files':[f.name for f in p.iterdir() if f.is_file() and f.suffix in ('.csv','.xlsx','.json','.jsonl')],
                     'updated':dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='minutes')}
                    for p in sorted(self.base.iterdir(),reverse=True) if p.is_dir()][:40]

    def report_file(self,run,name):
        if not (isinstance(run,str) and re.fullmatch(r'GUIDED_(ACC|GYRO)_[0-9]{8}_[0-9]{6}_[a-f0-9]{6}',run)):
            raise ValueError('工况目录不合法')
        if not (isinstance(name,str) and re.fullmatch(r'[a-zA-Z0-9_]+\.(json|csv|xlsx|jsonl)',name)):
            raise ValueError('报告文件名不合法')
        p=(self.base/run/name).resolve()
        if p.parent!=(self.base/run).resolve() or not p.is_file():
            raise FileNotFoundError('报告文件不存在')
        return p
