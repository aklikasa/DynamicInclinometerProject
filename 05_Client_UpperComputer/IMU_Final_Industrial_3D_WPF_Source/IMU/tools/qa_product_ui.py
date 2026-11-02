"""Non-Windows structural checks: not a substitute for WPF compilation or hardware acceptance."""
from pathlib import Path
import xml.etree.ElementTree as ET
import re,sys
root=Path(__file__).resolve().parents[1]
app=root/'src/DynamicInclinometer.App'
x='{http://schemas.microsoft.com/winfx/2006/xaml}'
checks=[]
def test(label,ok,detail=''):
 checks.append(bool(ok)); print(('PASS' if ok else 'FAIL'),label,detail)

for p in list(app.rglob('*.xaml')):
 try:
  doc=ET.parse(p)
  test(f'XML parse {p.relative_to(root)}',True)
 except Exception as e:
  test(f'XML parse {p.relative_to(root)}',False,str(e))

p=app/'App.xaml'
doc=ET.parse(p)
res=next(ch for ch in doc.getroot() if ch.tag.endswith('}Application.Resources'))
test('App.xaml resource collection contains no literal text',not (res.text or '').strip() and all(not (ch.tail or '').strip() for ch in res))
keys={c.attrib.get(x+'Key') for c in res if c.attrib.get(x+'Key')}
test('Resource keys unique',len(keys)==len([c for c in res if c.attrib.get(x+'Key')]))
for needed in ['LiquidGlassCard','NavAction','NavSelected','PanelHeading','MetricLabel','PrimaryAction','DangerAction','FieldLabel','GlassCard']:
 test('App resource '+needed,needed in keys)

controls=(app/'Controls/LiquidGlassPane.cs').read_text(encoding='utf8')
test('Correct control namespace', 'namespace DynamicInclinometer.App.Controls;' in controls)
test('Name scope controlled via ContentControl', 'LiquidGlassPane : ContentControl' in controls)
ui=ET.parse(app/'MainWindow.xaml')
xamltext=(app/'MainWindow.xaml').read_text(encoding='utf8')
code=(app/'MainWindow.xaml.cs').read_text(encoding='utf8')
event_names=set();names={}
for element in ui.getroot().iter():
 name=element.attrib.get(x+'Name')
 if name:
  names[name]=names.get(name,0)+1
 for attr in ['Click','ValueChanged','SizeChanged','SelectionChanged','Loaded']:
  if attr in element.attrib:event_names.add(element.attrib[attr])
test('Main Window x:Name globally unique',all(v==1 for v in names.values()))
missing=[h for h in sorted(event_names) if not re.search(r'\b'+re.escape(h)+r'\s*\(',code)]
test('Main Window event handlers exist',not missing,str(missing))
for name in ['MainTabs','LiquidScene','StatusLabel','ImuPort','SerialId','CalibrationText','RollText','PitchText',
             'YawText','QuickInnerAngleText','QuickOuterAngleText','SampleRateText','ProcessedCountText',
             'PlotCanvas','RollLine','PitchLine','AttitudeViewport','DeviceVisual','ReferenceAxesVisual',
             'TurntablePanel','TimingChoice','OdrInput','ResearchOverride','FilterDiagnostic','RecordPathText',
             'RunLog','LogExpander','OutputStatusText','FusedOutputButton','AbsoluteAngleButton','RelativeAngleButton',
             'ReferenceModeText','AdvancedPanel','NavMonitorButton','NavTurntableButton','GlassGpuToggleButton',
             'GlassStrengthSlider','GlassStatusText']:
 test('Main Window retains '+name,name in names)
test('No auto-test UI label',not any(t in xamltext for t in ['自动测试','自动正弦测试','开始自动测试']))
test('Readings not hard-coded as plausible numeric data', 'Text="--.---°"' in xamltext and 'Text="0.000°"' not in xamltext)
test('Measurement values tied to actual fused data', 'RollText.Text=gaugeLive?' in code and 'PitchText.Text=gaugeLive?' in code and 'YawText.Text=gaugeLive' in code)
test('Serial navigation genuinely routed', all(f'void {name}(' in code for name in ['NavMonitor_Click','NavTurntable_Click','NavSettings_Click','NavRecords_Click']))
test('Tab navigation indices exactly 0 and 1', 'MainTabs.SelectedIndex=2;' not in code)
test('Existing ABS REL state retained','TiltReferenceMath.RelativeTo' in code and '_relativeZero' in code)
test('ESKF remains wired','_engine.Mode=ProcessingMode.Eskf;' in code)
test('Real data freshness visible','ageSeconds>1.5' in code and 'SYNTHETIC' in code)
test('Source continues to use native GPU shader','PixelShader' in (app/'Effects/LiquidGlassEffect.cs').read_text())
test('Source has launch wrapper','<UseAppHost>true</UseAppHost>' in (app/'DynamicInclinometer.App.csproj').read_text())
test('User supplied manual table code retained',(app/'TurntableControlView.xaml.cs').exists())

bad=len([a for a in checks if not a])
print(f'\nUI QA: {len(checks)-bad}/{len(checks)} checks passed')
sys.exit(bool(bad))
