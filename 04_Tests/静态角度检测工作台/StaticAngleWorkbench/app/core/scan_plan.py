"""静态角度检查方案：仅生成计划，不触发任何硬件动作。"""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ScanPoint:
    channel: str
    inner_deg: float
    outer_signed_deg: float
    outer_command_deg: float
    settle_seconds: float
    sample_seconds: float

def make_scan_plan(sample_seconds: float = 5., settle_seconds: float = 3., step_deg: int = 10) -> list[ScanPoint]:
    if 360 % step_deg or not (0 < sample_seconds <= 600) or not (0 <= settle_seconds <= 600):
        raise ValueError('步进必须整除 360，时间参数须在有效范围内')
    return [ScanPoint(channel, float(inner), float(angle), float(angle % 360), settle_seconds, sample_seconds)
            for channel, inner in [('Y',0), ('X',90)] for angle in range(-180,181,step_deg)]

def save_scan_plan(points: list[ScanPoint], path: str | Path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['通道','内轴目标_deg','外轴逻辑角度_deg','外轴指令角度_0到360','静置秒数','采样秒数'])
        for p in points:
            writer.writerow([p.channel,p.inner_deg,p.outer_signed_deg,p.outer_command_deg,p.settle_seconds,p.sample_seconds])
