# -*- coding: utf-8 -*-
"""Qt-free R7 ambient auto sequencer for supervised 2TD-600 commissioning.

This controller reuses the physical R7 COM/DLL handle and original numerical
plan/capture/report modules. It NEVER opens a second COM port. All actions
run in a single monitored worker thread. A web browser closing cannot be used
as an E-STOP; a physical E-STOP remains mandatory.

Hardware auto-run is deliberately gated by an onsite commissioning file and
explicit operator confirmation. An offline test is NOT hardware qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import threading
import time

ROOT=Path(__file__).resolve().parent.parent
# File is intentionally absent on installation. Do not silently enable motors.
COMMISSION_FILE=ROOT/'native_web_data'/'2TD600_SITE_COMMISSIONED.json'


@dataclass
class AutoError(RuntimeError):
    reason: str
    def __str__(self): return self.reason


class AmbientAuto:
    def __init__(self, service, guided, sleep=time.sleep, clock=time.monotonic):
        self.s=service
        self.g=guided
        self._sleep=sleep
        self.clock=clock
        self.lock=threading.RLock()
        self.abort_event=threading.Event()
        self.worker=None
        self.state='idle'
        self.phase=''
        self.message=''
        self.run_id=None
        self.completed_run_ids=[]
        self.kind=None
        self._remaining=[]
        self._start_request=None
        self.started=None
        self.last_error=''
        self._last_imu_count=None
        self._last_imu_progress=None
        self._last_progress_persist=0.

    def is_active(self):
        with self.lock:
            return self.state in ('starting','running','stopping')

    def _set(self, phase, message=''):
        with self.lock:
            self.phase=phase
            self.message=message
        try:self.g._audit('AUTO_PHASE',f'{phase}: {message}')
        except Exception:pass

    def status(self):
        with self.lock:
            return {'state':self.state,'phase':self.phase,'message':self.message,
                    'run_id':self.run_id,'completed_run_ids':list(self.completed_run_ids),
                    'kind':self.kind,'last_error':self.last_error,
                    'active':self.state in ('starting','running','stopping'),
                    'hardware_commissioned':self._is_commissioned(),
                    'notice':'实机自动运动须现场监护；软件停车不能代替硬件急停；不自动写入PCB系数。'}

    def _is_commissioned(self):
        try:
            d=json.loads(COMMISSION_FILE.read_text(encoding='utf-8'))
            # The file is an explicit onsite commissioning record, not a device ID.
            return d.get('model')=='2TD-600' and d.get('motion_validation')=='PASSED_ON_PHYSICAL_RIG' \
                and d.get('e_stop_test')=='PASSED_ON_PHYSICAL_RIG' and bool(d.get('operator'))
        except (OSError,ValueError,TypeError):return False

    def start(self, request):
        if not isinstance(request,dict):raise ValueError('请求必须是对象')
        if request.get('safety_ack')!='PHYSICAL_ESTOP_READY' or request.get('motion_ack')!='SUPERVISED_AUTO_MOVEMENT':
            raise ValueError('需要现场硬件急停确认和单独的自动运动确认')
        if not self._is_commissioned():
            raise RuntimeError('尚未完成 2TD600 现场运动、停车和急停验收，自动执行锁定。见《现场启用与验收.md》')
        with self.lock:
            if self.state in ('starting','running','stopping'):
                raise RuntimeError('已经存在自动任务')
            with self.s.td_motion_lock:
                if self.s.td_motion.get('state') not in ('idle','stopped','complete'):
                    raise RuntimeError('存在手动转台运动，不能启动自动工况')
            if self.g.session and self.g.session.get('state') in ('ready','collecting','analyzing'):
                raise RuntimeError('存在未完成的人工采样会话，先取消当前任务')
            self.abort_event.clear()
            # Two-sensor job runs ACC then GYRO in separate real hardware sessions.
            # They retain independent model and report provenance.
            kind=request.get('kind')
            if kind not in ('acc','gyro','both'):
                raise ValueError('标定类型必须为 ACC、GYRO 或 ACC+GYRO')
            self.kind=kind
            self._start_request=dict(request)
            self._remaining=['gyro'] if kind=='both' else []
            self.completed_run_ids=[]
            start_request=dict(request,kind='acc' if kind=='both' else kind)
            guided=self.g.start(start_request)
            self.run_id=guided['run_id']
            self.g.session['acquisition_mode']='SUPERVISED_AUTO_REAL_HARDWARE'
            self.g._store()
            self.started=self.clock()
            self.last_error=''
            self.state='starting'
            self.phase='preflight'
            self.message='正在执行真实设备前置检查'
            self._last_imu_count=None
            self._last_imu_progress=self.clock()
            self.worker=threading.Thread(target=self._run,daemon=True,name='2TD600-ambient-auto')
            self.worker.start()
        return self.status()

    def request_abort(self):
        with self.lock:
            if self.state not in ('starting','running','stopping'):
                raise RuntimeError('当前没有正在执行的自动标定')
            self.abort_event.set()
            self.state='stopping'
            self.message='已经请求停车；等待双轴实际速度反馈变为零'
        return self.status()

    def _check_cancel(self):
        if self.abort_event.is_set():raise AutoError('操作员中止任务')

    def _health(self, allow_abort=False):
        if not allow_abort:self._check_cancel()
        st=self.s.status()
        if not st['imu']['reading'] or not st['td']['reading']:
            raise AutoError('PCB 或转台失去实时反馈')
        age=st['td'].get('feedback_age_ms')
        if age is None or age>750:
            raise AutoError(f'转台反馈过期（{age} ms）')
        # Real sensor data must continue changing; stale cached readings are not enough.
        n=st['imu'].get('success_count')
        if isinstance(n,int):
            if n!=self._last_imu_count:
                self._last_imu_count=n;self._last_imu_progress=self.clock()
            elif self.clock()-self._last_imu_progress>1.5:
                raise AutoError('PCB 实时有效帧计数超过 1.5 秒未更新')
        with self.s.td_io_lock:
            states=self.s._td_safety_snapshot()
            td=self.s._td_driver()
            for name,axis in (('inner',td.INNER_ROTATION_AXIS),('outer',td.OUTER_ROTATION_AXIS)):
                lock_flag=td.twoTD600_getAxisLock(axis)
                if type(lock_flag) is not bool or lock_flag:
                    raise AutoError(name+' 轴处于机械锁紧或锁紧反馈未知')
                if abs(states[name]['speed'])>10.3:
                    raise AutoError(name+' 轴反馈速度超过 R7 的 10°/s 软件限速')
        return states

    def _await_fresh_imu_after_processing(self):
        """Require a new physical PCB success counter before any new motion.

        Model fitting/report I/O can occupy the acquisition callback. This
        check waits for the original live serial reader to resume instead of
        treating a previously cached frame as fresh sensor evidence.
        """
        st=self.s.status()
        previous=st['imu'].get('success_count')
        if not isinstance(previous,int):
            raise AutoError('原 PCB 后端未提供有效帧计数，禁止启动自动运动')
        deadline=self.clock()+2.5
        while self.clock()<deadline:
            self._check_cancel()
            cur=self.s.status()
            age=cur['td'].get('feedback_age_ms')
            if not cur['td']['reading'] or age is None or age>750:
                raise AutoError('等待 PCB 新帧期间转台反馈失联')
            now=cur['imu'].get('success_count')
            if cur['imu']['reading'] and isinstance(now,int) and now>previous:
                self._last_imu_count=now
                self._last_imu_progress=self.clock()
                return
            self._sleep(.12)
        raise AutoError('无法确认 PCB 持续输出新的有效数据帧；禁止下一工况运动')

    def _wait(self, seconds):
        end=self.clock()+seconds
        while self.clock()<end:
            self._health()
            self._sleep(min(.12,max(.005,end-self.clock())))

    def _wait_pred(self,predicate,deadline,label,stability=.6,allow_abort=False):
        since=None
        while True:
            axes=self._health(allow_abort=allow_abort)
            now=self.clock()
            if predicate(axes):
                since=now if since is None else since
                if now-since>=stability:return axes
            else:since=None
            if now>deadline:raise AutoError(label+' 超时，未得到实际反馈确认')
            self._sleep(.12)

    def _axis(self,name):
        d=self.s._td_driver()
        return d.INNER_ROTATION_AXIS if name=='inner' else d.OUTER_ROTATION_AXIS

    @staticmethod
    def _angle_error(a,b):return (float(a)-float(b)+180.)%360.-180.

    def _stop_both(self):
        # No reliance on HTTP request/browser to send the last stop.
        if not self.s.td_connected:return False
        with self.s.td_motion_lock:
            with self.s.td_io_lock:
                d=self.s._td_driver()
                results=[d.twoTD600_SetAxisStop(self._axis(name)) for name in ('inner','outer')]
        return all(x is True for x in results)

    def _confirm_stop(self, seconds=12):
        try:
            self._wait_pred(lambda states: all(abs(v['speed'])<.05 for v in states.values()),
                            self.clock()+seconds,'双轴停车',stability=.5,allow_abort=True)
            return True
        except Exception:return False

    def _position(self, axis, target, speed=3.):
        states=self._health()
        other='outer' if axis=='inner' else 'inner'
        if abs(states[other]['speed'])>.05 or abs(states[axis]['speed'])>.05:
            raise AutoError('双轴未停稳，禁止发下一条位置指令')
        if axis=='inner' and abs(self._angle_error(states['outer']['position'],0))>.2:
            raise AutoError('内轴运动前外轴必须处于零位')
        delta=abs(states[axis]['position']-float(target))
        if delta<=.2:return
        if not -360.0<=target<=360.0:
            raise AutoError('位置目标超出当前软件配置 ±360°')
        if not .01<=speed<=10.:raise AutoError('工艺定位速度超出 R7 上限')
        self._set('position',f'{axis} → {target:g}° / {speed:g}°/s')
        with self.s.td_motion_lock:
            self._check_cancel()  # serialized against operator software-stop
            with self.s.td_io_lock:
                td=self.s._td_driver()
                if td.twoTD600_SetAxisPosition(self._axis(axis),float(target),float(speed)) is not True:
                    raise AutoError(axis+' 轴位置指令被 DLL 拒绝')
        deadline=self.clock()+max(18.,delta/speed*3.+15.)
        def arrived(a):
            if abs(a[axis]['speed'])>=.05 or abs(a[other]['speed'])>=.05:return False
            if abs(self._angle_error(a[axis]['position'],target))>.2:return False
            with self.s.td_io_lock:
                return self.s._td_driver().twoTD600_getAxisMoveInPlace(self._axis(axis)) is True
        self._wait_pred(arrived,deadline,axis+' 轴位置到位')

    def _step_position(self,step):
        # Manual §3.2: inner rotation is allowed only with outer axis at zero.
        # Always park outer at zero before changing inner, then position outer.
        self._position('outer',0.)
        self._position('inner',float(step['inner_deg']))
        self._position('outer',float(step['outer_deg']))
        self._set('settle','等待 R7 工艺静置时间')
        self._wait(float(self.g.session['profile']['timing']['settle_seconds']))

    def _run_rate(self,step):
        axis=step['rotation_axis']
        speed=float(step['target_rate_dps'])
        profile=self.g.session['profile']
        if not math.isfinite(speed) or abs(speed)>min(10.,float(profile['rates']['maximum_command_rate_dps'])):
            raise AutoError('GYRO 工况速度超过原 R7 保护限值')
        other='inner' if axis=='outer' else 'outer'
        axes=self._health()
        if any(abs(a['speed'])>.05 for a in axes.values()):
            raise AutoError('GYRO 速率开始前双轴必须静止')
        if axis=='inner' and abs(self._angle_error(axes['outer']['position'],0))>.2:
            raise AutoError('内轴连续转动要求外轴零位静止')
        self._set('rate_command',f'{axis} {speed:+g}°/s，加速度 1°/s²')
        with self.s.td_motion_lock:
            self._check_cancel()  # no new rate command after stop was requested
            with self.s.td_io_lock:
                d=self.s._td_driver()
                if d.twoTD600_SetAxisVelocity(self._axis(axis),speed,1.) is not True:
                    raise AutoError('厂家 DLL 拒绝 GYRO 速率指令')
        try:
            tol=max(.2,abs(speed)*.15)
            self._wait_pred(lambda a: abs(a[axis]['speed']-speed)<=tol and abs(a[other]['speed'])<.05,
                            self.clock()+30.,'GYRO 实际速率稳定',stability=.7)
            self._set('rate_capture',step['step_id']+' 正在同步采集真实六轴帧')
            self.g.begin()
            secs=float(self.g.status()['required_seconds'])
            self._wait(secs+.05)
            result=self.g.finish()
        finally:
            if not self._stop_both():
                raise AutoError('速率段结束时停车指令未确认；请立即检查硬件急停')
            self._set('rate_stop','等待双轴速度降至零')
            self._wait_pred(lambda a:all(abs(v['speed'])<.05 for v in a.values()),
                            self.clock()+20.,'速率段停车',stability=.6)
        return result

    def _run_static(self,step):
        self._set('static_capture',step['step_id']+' 正在采集真实 PCB 帧')
        self.g.begin()
        secs=float(self.g.status()['required_seconds'])
        self._wait(secs+.05)
        return self.g.finish()

    def _run(self):
        try:
            self._await_fresh_imu_after_processing()
            self._health()
            with self.lock:self.state='running'
            self._set('prepare','双轴机械找零状态已验证；逐轴回到 0°')
            self._position('outer',0.)
            self._position('inner',0.)
            self._wait(float(self.g.session['profile']['timing']['settle_seconds']))
            while True:
                self._check_cancel()
                session=self.g.session
                if session is None:raise AutoError('采集会话意外丢失')
                if session['state']=='complete':
                    with self.lock:self.completed_run_ids.append(session['run_id'])
                    if self._remaining:
                        self._await_fresh_imu_after_processing()
                        self._health()  # never launch next sensor against stale feedback
                        next_kind=self._remaining.pop(0)
                        self._set('switch_sensor',f'{session["kind"].upper()} 已完成，核查设备后开始 {next_kind.upper()}')
                        next_result=self.g.start(dict(self._start_request,kind=next_kind))
                        self.g.session['acquisition_mode']='SUPERVISED_AUTO_REAL_HARDWARE'
                        self.g._store()
                        with self.lock:self.run_id=next_result['run_id']
                        self._position('outer',0.)
                        self._position('inner',0.)
                        self._wait(float(self.g.session['profile']['timing']['settle_seconds']))
                        continue
                    with self.lock:
                        self.state='completed';self.phase='report'
                        self.message='全部工况完成，ACC/GYRO 模型比较及独立报告已保存（未写入PCB）'
                    return
                if session['state']=='analysis_failed':raise AutoError('模型分析失败，查看任务日志')
                index=session['index']
                if index>=len(session['steps']):raise AutoError('工况进度不一致')
                step=session['steps'][index]
                self._set('target',f'{index+1}/{len(session["steps"])} · {step["step_id"]}')
                self._step_position(step)
                retries=int(session['profile']['quality'][('static_sample_max_retries' if step['mode']=='static' else 'rate_sample_max_retries')])
                for attempt in range(retries+1):
                    self._check_cancel()
                    if attempt:
                        self._set('retry',f'{step["step_id"]} 质量重采 {attempt}/{retries}')
                        self._step_position(step)
                    result=self._run_static(step) if step['mode']=='static' else self._run_rate(step)
                    if result['index']>index:break
                    if result['state'] not in ('ready','collecting'):
                        raise AutoError('采样质量状态异常：'+result['state'])
                    if attempt==retries:
                        raise AutoError(f'{step["step_id"]} 质量重试耗尽；{result.get("last_error", "")}' )
        except Exception as exc:
            self.abort_event.set()
            with self.lock:
                self.state='stopping';self.phase='stopping';self.last_error=str(exc)
            try:sent=self._stop_both()
            except Exception:sent=False
            confirmed=self._confirm_stop() if sent else False
            if self.g.session and self.g.session.get('state') in ('ready','collecting'):
                try:self.g.cancel()
                except Exception:pass
            with self.lock:
                self.state='aborted' if confirmed else 'fault'
                self.phase='stopped' if confirmed else 'STOP_UNCONFIRMED'
                self.message=str(exc)+('；双轴反馈已确认停止' if confirmed else '；无法确认停车，请使用现场硬件急停！')
            try:self.g._audit('AUTO_ABORT',self.message)
            except Exception:pass
        finally:
            # Permit manual controls again only when no automatic motion remains.
            self.abort_event.clear()

