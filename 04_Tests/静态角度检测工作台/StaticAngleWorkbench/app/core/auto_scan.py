"""Feedback-driven, nonblocking automatic sweep controller.
No automatic motor-enable, no unverified hardware homing command. Encoder 0 positioning is not mechanical homing.
"""
from __future__ import annotations
from datetime import datetime
import math
import time
from PySide6.QtCore import QObject, QTimer, Signal
from .scan_plan import make_scan_plan
from .measurement import process_point, wrap_deg
from app.devices.turntable_driver import INNER, OUTER

def distance(a,b): return abs(wrap_deg(a-b))

class AutoScan(QObject):
    notice=Signal(str)
    progress=Signal(int,int,str)
    finished=Signal(str,str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer=QTimer(self); self.timer.setInterval(80); self.timer.timeout.connect(self.tick)
        self.active=False; self.rows=[]; self.frames=[]; self.point_index=0
        self.last_frame_monotonic=0; self.last_fb_monotonic=0

    def start(self, worker, cal, settle=3., sample=5., speed=2., step=10):
        if self.active: raise RuntimeError('自动检测已在运行')
        self.worker=worker; self.cal=cal; self.settle=settle; self.sample=sample; self.speed=speed
        self.points=make_scan_plan(sample,settle,step)
        self.rows=[]; self.frames=[]; self.point_index=0; self.active=True
        self.fb=None; self.phase='prepare'; self.phase_time=time.monotonic(); self.pending=None
        self.failed_reason=''; self.last_frame_monotonic=0; self.last_fb_monotonic=0
        self.notice.emit('自动检测启动：执行编码器 0° 定位检查；此操作不是机械寻零')
        self.timer.start()

    def feed(self,frame):
        if not self.active or not frame.valid: return
        self.last_frame_monotonic=time.monotonic()
        if self.phase=='sample' and frame.accel_samples_g:
            self.frames.append(frame.accel_samples_g)

    def feedback(self,fb):
        if self.active:
            self.fb=fb; self.last_fb_monotonic=time.monotonic()

    def command_result(self, name, ok, message):
        if not self.active:
            return
        if self.phase == 'stopping' and name == 'stop_all':
            self.pending = None
            if ok:
                self._finish(self.stop_status, self.failed_reason)
            else:
                self._finish('危险-停车未确认', self.failed_reason + '；停车失败：' + message)
            return
        if self.pending is None or name != self.pending:
            return
        self.pending = None
        if not ok:
            self.abort('转台命令失败：' + message)

    def _request_stop(self, status, reason=''):
        if not self.active or self.phase == 'stopping':
            return
        self.stop_status = status
        self.failed_reason = reason
        self.phase = 'stopping'
        self.phase_time = time.monotonic()
        self.pending = 'stop_all'
        self.notice.emit('自动检测停止运动：' + (reason or '采点结束') + '；正在等待停车确认')
        if not self.worker.submit('stop_all'):
            self._finish('危险-停车未确认', '停车指令未成功进入队列')

    def abort(self, reason='用户终止'):
        self._request_stop('中止', reason)

    def _finish(self, status, reason=''):
        self.active = False
        self.timer.stop()
        self.finished.emit(status, reason)

    def _move(self,axis,angle):
        if self.pending: return False
        self.worker.submit('move',axis,float(angle)%360,self.speed)
        self.pending='move'
        self.phase_time=time.monotonic()
        return True

    def _stopped_at(self,axis,target):
        if self.fb is None: return False
        v=self.fb[axis]
        return bool(v['normal'] and v['enabled'] and v['in_place'] and not v['driver_fault']
                    and abs(v['speed'])<.05 and distance(v['position'],target)<.15)

    def tick(self):
        if not self.active: return
        now=time.monotonic()
        if self.phase == 'stopping':
            if now-self.phase_time > 20.0:
                self._finish('危险-停车未确认', '等待DLL停车及反馈超时；请检查实体急停')
            return
        if not self.fb or now-self.last_fb_monotonic>2.0:
            if now-self.phase_time>6: self.abort('转台反馈超时')
            return
        for axis in ('inner','outer'):
            x=self.fb[axis]
            if not x['normal'] or not x['enabled'] or any(x.get(k) for k in ('driver_fault','up_limit','down_limit','over_speed','over_diff')):
                self.abort(f'{axis} 异常/未使能/触发限位'); return
        if self.phase=='prepare':
            self._move(INNER,0); self.phase='zero_inner'; return
        if self.phase=='zero_inner':
            if self.pending: return
            if now-self.phase_time>185/self.speed+25: self.abort('内轴编码器 0° 定位超时'); return
            if self._stopped_at('inner',0):
                self._move(OUTER,0); self.phase='zero_outer'
            return
        if self.phase=='zero_outer':
            if self.pending: return
            if now-self.phase_time>185/self.speed+25: self.abort('外轴编码器 0° 定位超时'); return
            if self._stopped_at('outer',0): self.phase='next'; self.phase_time=now
            return
        if self.phase=='next':
            if self.point_index>=len(self.points):
                self._request_stop('完成'); return
            p=self.points[self.point_index]
            if self.point_index==37 and self._stopped_at('outer',0) is False:
                self._move(OUTER,0); self.phase='between_zero'; return
            if not self._stopped_at('inner',p.inner_deg):
                self._move(INNER,p.inner_deg); self.phase='target_inner'; return
            self._move(OUTER,p.outer_command_deg); self.phase='target_outer'; return
        if self.phase=='between_zero':
            if self.pending: return
            if self._stopped_at('outer',0): self.phase='next'
            elif now-self.phase_time>185/self.speed+25: self.abort('轮次切换归零超时')
            return
        if self.phase=='target_inner':
            if self.pending: return
            p=self.points[self.point_index]
            if self._stopped_at('inner',p.inner_deg): self.phase='next'
            elif now-self.phase_time>185/self.speed+25: self.abort('内轴定位超时')
            return
        if self.phase=='target_outer':
            if self.pending: return
            p=self.points[self.point_index]
            if self._stopped_at('outer',p.outer_command_deg):
                self.phase='settle'; self.phase_time=now
            elif now-self.phase_time>185/self.speed+25: self.abort('外轴定位超时')
            return
        if self.phase=='settle':
            if now-self.phase_time>=self.settle:
                self.phase='sample'; self.phase_time=now; self.frames=[]
                self.sample_start=datetime.now().isoformat(timespec='seconds')
            return
        if self.phase=='sample':
            if now-self.last_frame_monotonic>2: self.abort('IMU 数据中断超过 2 秒'); return
            if now-self.phase_time<self.sample: return
            p=self.points[self.point_index]
            result=dict(channel=p.channel,inner_deg=p.inner_deg,outer_signed_deg=p.outer_signed_deg,
                        inner_actual=self.fb['inner']['position'],outer_actual=self.fb['outer']['position'],
                        started_at=self.sample_start,ended_at=datetime.now().isoformat(timespec='seconds'))
            # Reference uses ACTUAL outer-axis feedback, not merely commanded angle.
            actual_ref=wrap_deg(result['outer_actual'])
            if distance(result['outer_actual'],p.outer_command_deg)>.15:
                self.abort('采样时外轴偏离目标'); return
            try:
                result.update(process_point(self.frames,self.cal,p.channel,actual_ref))
                result['ok']=True
            except Exception as exc:
                result.update(ok=False,message=str(exc))
            self.rows.append(result)
            self.point_index+=1
            self.progress.emit(self.point_index,len(self.points),f'{p.channel} · {p.outer_signed_deg:+.0f}° · {"正常" if result["ok"] else "异常"}')
            if not result['ok']:
                self.abort('采样质量失败：'+result['message']); return
            self.phase='next'; self.phase_time=now
