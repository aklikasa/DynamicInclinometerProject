"""Two-level 3*MAD robust aggregation and circular angle comparison."""
from __future__ import annotations
import math
import statistics as st

def median_filter3(samples, sigma=3.0):
    if not samples: return [], 0
    centers = [st.median([v[j] for v in samples]) for j in range(3)]
    scales = [1.4826*st.median([abs(v[j]-centers[j]) for v in samples]) for j in range(3)]
    kept = [v for v in samples if all(abs(v[j]-centers[j]) <= sigma*max(scales[j], 1e-6) for j in range(3))]
    return kept, len(samples)-len(kept)

def mean3(samples):
    return tuple(st.fmean(v[j] for v in samples) for j in range(3))

def wrap_deg(deg):
    return (deg+180)%360-180

def angle_error(measured, reference):
    return wrap_deg(measured-reference)

def process_point(frames, calibration, channel, reference_deg, minimum_frames=50, maximum_reject=0.1):
    if len(frames) < minimum_frames: raise ValueError(f'帧数不足 {len(frames)}/{minimum_frames}')
    rows=[]; raw_count=accepted=0
    for f in frames:
        raw_count += len(f)
        good, _ = median_filter3(f)
        accepted += len(good)
        if good: rows.append(mean3(good))
    good_frames, dropped = median_filter3(rows)
    if len(good_frames)<minimum_frames: raise ValueError(f'有效帧不足 {len(good_frames)}/{minimum_frames}')
    rejection=1-(accepted/raw_count)*(len(good_frames)/len(rows))
    if rejection > maximum_reject: raise ValueError(f'异常值剔除率 {rejection:.1%} 超出上限 {maximum_reject:.1%}')
    raw=mean3(good_frames); corr=calibration.correct(raw)
    norm=math.sqrt(sum(v*v for v in corr))
    if not .8 <= norm <= 1.2: raise ValueError(f'加速度模长 {norm:.4f} g 异常')
    if channel == 'Y': measured=math.degrees(math.atan2(corr[1], corr[2]))
    elif channel == 'X': measured=math.degrees(math.atan2(corr[0], corr[2]))
    else: raise ValueError('无效检测通道')
    # Actual axis sign and mounting offset must be established by physical verification.
    return dict(raw=raw,corrected=corr,measured_deg=wrap_deg(measured),
                reference_deg=wrap_deg(reference_deg),error_deg=angle_error(measured,reference_deg),
                norm_g=norm,frames=len(frames),accepted_frames=len(good_frames),
                raw_samples=raw_count,accepted_samples=accepted,rejected_fraction=rejection,
                std_g=tuple(st.pstdev(v[j] for v in good_frames) for j in range(3)))
