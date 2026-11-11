# -*- coding: utf-8 -*-
"""Complete 28-candidate structure catalog and auditable coefficient export.

No fitting, selection or approval logic here. Catalog entries describe precisely
what the matching thermal_model_selection.py code actually fits.
"""
from __future__ import annotations

FAMILIES={'B':'仅零偏随温度','C':'零偏与3个对角比例随温度','D':'零偏与完整3×3矩阵随温度'}
INPUTS={
    'T0':('原始芯片温度','Te = Tchip'),
    'T1':('PV等效线性芯片温度','Te = 25 + c0 + c1·(Tchip−25)/50'),
    'T2':('PV等效二次芯片温度','Te = 25 + c0 + c1·u + c2·u², u=(Tchip−25)/50'),
}

def full_catalog():
    """One baseline plus 3 effective-temperature inputs × 3 families × 3 orders."""
    result=[]
    for temp, family, degree in [('T0','A',0)]+[(t,f,d) for t in ('T0','T1','T2') for f in 'BCD' for d in (1,2,3)]:
        mid='A0' if family=='A' else f'{temp}-{family}{degree}'
        terms=' + '.join((('p0' if k==0 else f'p{k}·(Te−25)'+(f'^{k}' if k>1 else '')) for k in range(degree+1)))
        if family=='A':
            structure='F=F25（常数完整3×3）; b=b25（常数3维）'
            change='F全部固定；b全部固定'
            n=12
        elif family=='B':
            structure=f'F(Te)=F25（完整常数3×3）；b(Te)逐轴按{degree}阶多项式变化'
            change='仅3个零偏随温度；9个矩阵元素固定'
            n=9+3*(degree+1)
        elif family=='C':
            structure=f'F(Te)非对角6项固定；对角3项与b(Te)的3项均按{degree}阶多项式变化'
            change='3个比例系数+3个零偏随温度；6个轴间耦合固定'
            n=6+6*(degree+1)
        else:
            structure=f'F(Te)九个元素、b(Te)三个元素各自按{degree}阶多项式变化'
            change='完整9个矩阵元素和3个零偏均随温度'
            n=12*(degree+1)
        formula='raw = F(Te)·reference + b(Te)；校正 reference = F(Te)^(-1)·(raw−b(Te))'
        result.append({'id':mid,'input_id':temp,'input_name':INPUTS[temp][0],
                       'temperature_formula':INPUTS[temp][1], 'family':family,
                       'degree':degree,'structure':structure,'change':change,
                       'parameter_polynomial':terms,'parameter_count':n,
                       'input_coeff_count':0 if temp=='T0' else (2 if temp=='T1' else 3),
                       'calibration_formula':formula,
                       'note':'A0用25℃拟合实测参数固定全温区' if family=='A'
                              else ('PV等效温度只在标定时使用温箱PV，部署只输入芯片温度' if temp!='T0' else '运行使用原始芯片温度；拒绝外推')})
    assert len(result)==28 and len(set(x['id'] for x in result))==28
    return result

def all_candidate_coefficients(selection):
    """Raw numeric coefficients; never silently synthesize missing models."""
    records=[]
    for sensor, info in selection.get('sensors',{}).items():
        path_models=info.get('all_candidate_models',{})
        for id_, model in path_models.items():
            for kind,key in (('零偏b','bias_coeff'),('矩阵F','forward_coeff')):
                coeff=model.get(key,[])
                if kind=='零偏b':
                    for axis, params in enumerate(coeff):
                        for k,value in enumerate(params):
                            records.append((sensor.upper(),id_,kind,f'{axis}', '',k,float(value)))
                else:
                    for r,line in enumerate(coeff):
                        for c,params in enumerate(line):
                            for k,value in enumerate(params):
                                records.append((sensor.upper(),id_,kind,f'{r}',f'{c}',k,float(value)))
            transform=model.get('temperature_input',{})
            for k, val in enumerate(transform.get('coefficients_c',[])):
                records.append((sensor.upper(),id_,'温度输入映射c','','',k,float(val)))
    return records
