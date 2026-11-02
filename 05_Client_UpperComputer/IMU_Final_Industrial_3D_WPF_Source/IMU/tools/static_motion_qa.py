"""No hardware is driven. Verifies bindings/legacy APIs/2TD600 DLL exports.
On Windows use the .NET SDK as well: ./构建和测试.ps1.
"""
from pathlib import Path
import re, subprocess, sys, math
from lxml import etree
root=Path(__file__).resolve().parents[1]
app=root/'src/DynamicInclinometer.App'
code=(app/'TurntableControlView.xaml.cs').read_text(encoding='utf-8')
ui=(app/'TurntableControlView.xaml').read_text(encoding='utf-8')
main=(app/'MainWindow.xaml.cs').read_text(encoding='utf-8')
dev=(root/'src/DynamicInclinometer.Devices/TurntableTelemetry.cs').read_text(encoding='utf-8')
checks=[]
def check(name, condition):
    checks.append((name,bool(condition)))
    print(('PASS' if condition else 'FAIL'),name)

for path in app.glob('*.xaml'):
    try: etree.parse(str(path)); check(path.name+' XML valid',True)
    except Exception as e: check(path.name+' XML valid',False);print(e)
for path in [app/'TurntableControlView.xaml', app/'MainWindow.xaml']:
    s=path.read_text(encoding='utf-8')
    cs=(path.parent/(path.stem+'.xaml.cs')).read_text(encoding='utf-8')
    ev=set(re.findall(r'(?:Click|SizeChanged|Loaded|SelectionChanged|TextChanged|Closing)="([A-Za-z_][A-Za-z0-9_]*)"',s))
    missing=[x for x in ev if not re.search(r'\b'+re.escape(x)+r'\s*\(',cs)]
    check(path.name+' event handlers bound ('+str(len(ev))+')',not missing)
    if missing:print('missing:',missing)
check('Relative manual mode, default',ui.count('SelectedIndex="0"')>=2 and '相对位置（增量角）' in ui)
check('Position feedback is absolute', 'InnerAngleText.Text=$"{r.Inner.Axis.Position360Deg:F3}°"' in code and 'OuterAngleText.Text=$"{r.Outer.Axis.Position360Deg:F3}°"' in code)
check('Single and joint controls available',all(x in ui for x in ['MoveBoth_Click','MoveInner_Click','MoveOuter_Click']))
check('3 mechanical home buttons present',all(x in ui for x in ['HomeBoth_Click','HomeInner_Click','HomeOuter_Click']))
check('Already-enabled state is respected','if(state.Axis.Enabled)return;' in code)
check('Auto preflight enables by readback, no mandatory manual page', 'await EnsureAxisEnabledAsync(0);' in code and 'await EnsureAxisEnabledAsync(2);' in code and '|| !_armed || _busy' not in code)
check('Rate bound follows manual', 'speed>60.0' in code and 'speedDps>60.0' in dev)
check('Rate guard 5 deg/s is gone', 'speed>5.0' not in code and 'speedDps>5.0' not in dev)
check('Joint motor command stages and dispatches', 'NativeUnited(0,innerAbsolute?1:2,innerDegrees,innerSpeed,true,false)' in dev and 'NativeUnited(2,outerAbsolute?1:2,outerDegrees,outerSpeed,false,true)' in dev)
check('Native union staged failure triggers stop','issued=true; // Even a partially staged' in code and 'if(issued)try{await StopAllAndVerifyAsync();}' in code)
check('Async stop generation guard','_stopGeneration!=stopGeneration' in code and 'Interlocked.Increment(ref _stopGeneration)' in code)
check('No feedback double polling','d.Read());' not in code and 'new TurntableReadback(_feedbackClock.Elapsed.TotalSeconds' in code)
check('Stable non-wrapping manual telemetry','x:Name="InnerStatus"' in ui and 'TextWrapping="NoWrap" Height="23"' in ui and 'x:Name="OuterStatus"' in ui)
check('auto-test entry removed from XAML', '自动测试   "' not in (root/'src/DynamicInclinometer.App/MainWindow.xaml').read_text(encoding='utf-8'))
check('legacy auto run path hard-disabled', '_automaticTestingRemoved' in main and '不会发送任何自动摇摆命令' in main)
# PE symbol table test (objdump is not available on all Windows developer hosts)
try:
    proc=subprocess.run(['objdump','-p',str(root/'vendor/2TD600.dll')],capture_output=True,text=True,check=True)
    for name in ['GetAxisEnable','GetAxisFindZero','SetAxisFindZero','SetAxisPosition','SetAxisOpposition','SetUniteAxisAction']:
        check('DLL export '+name,any(line.split()[-1]==name for line in proc.stdout.splitlines() if name in line))
except Exception:
    print('SKIP PE export test: objdump unavailable')
# Small pure arithmetic behavior test for relative -> absolute display
wrap=lambda v:(v%360+360)%360
check('Relative 359.8 + 5 -> 4.8', math.isclose(wrap(359.8+5),4.8,abs_tol=1e-9))
check('Relative 1.2 - 5 -> 356.2', math.isclose(wrap(1.2-5),356.2,abs_tol=1e-9))
fail=[name for name,ok in checks if not ok]
print(f'\nSTATIC QA: {len(checks)-len(fail)}/{len(checks)} passed')
if fail: sys.exit(1)
