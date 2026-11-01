"""加速度标定文件解析。与设备通讯解耦。"""
from __future__ import annotations
from dataclasses import dataclass
import json
import math
from pathlib import Path


def _vector(raw, n, field):
    if not isinstance(raw, list) or len(raw) != n or any(type(x) not in (float, int) or not math.isfinite(x) for x in raw):
        raise ValueError(f"{field} 必须是 {n} 个有限数字")
    return tuple(float(x) for x in raw)


@dataclass(frozen=True)
class Calibration:
    path: Path
    device_serial: str
    run_id: str
    verdict: str
    approved: bool
    bias: tuple[float, float, float]
    matrix: tuple[tuple[float, float, float], ...]

    @classmethod
    def load(cls, path: str | Path) -> 'Calibration':
        path = Path(path).resolve()
        obj = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(obj, dict):
            raise ValueError('JSON 根节点必须是对象')
        bias = _vector(obj.get('raw_accel_bias_g'), 3, 'raw_accel_bias_g')
        rows = obj.get('raw_to_platform_matrix')
        if not isinstance(rows, list) or len(rows) != 3:
            raise ValueError('raw_to_platform_matrix 必须是 3×3 矩阵')
        matrix = tuple(_vector(row, 3, 'raw_to_platform_matrix') for row in rows)
        a, b, c = matrix
        det = (a[0] * (b[1] * c[2] - b[2] * c[1])
               - a[1] * (b[0] * c[2] - b[2] * c[0])
               + a[2] * (b[0] * c[1] - b[1] * c[0]))
        if abs(det) < 1e-9:
            raise ValueError('校正矩阵不可逆或接近奇异')
        quality = obj.get('quality_gate') or {}
        if not isinstance(quality, dict):
            quality = {}
        return cls(path, str(obj.get('device_serial', '—')), str(obj.get('run_id', '—')),
                   str(quality.get('verdict', '未标注')),
                   bool(quality.get('approved_for_production', False)), bias, matrix)

    def correct(self, raw_g):
        """校准关系：a_P = M(raw_g - bias)。不计算检测角度。"""
        x = [float(raw_g[i]) - self.bias[i] for i in range(3)]
        return tuple(sum(row[j] * x[j] for j in range(3)) for row in self.matrix)
