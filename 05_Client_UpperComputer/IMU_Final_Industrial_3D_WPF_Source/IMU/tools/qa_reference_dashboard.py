"""Cross-platform structural checks for customer dashboard; not a Windows build or hardware certification."""
from pathlib import Path
import hashlib,re,sys,xml.etree.ElementTree as ET
from collections import Counter
root=Path(__file__).resolve().parents[1]
app=root/'src/DynamicInclinometer.App'
files={f.name:f for f in app.glob('*.xaml')}
cs=(app/'MainWindow.xaml.cs').read_text(encoding='utf-8')
view=(app/'TurntableControlView.xaml.cs').read_text(encoding='utf-8')
main=(app/'MainWindow.xaml').read_text(encoding='utf-8')
styles=(app/'App.xaml').read_text(encoding='utf-8')
checks=[]
def check(label,success):
 checks.append((label,bool(success)))
 print(('PASS' if success else 'FAIL')+' '+label)
for f in list(app.glob('*.xaml'))+list(app.glob('*.csproj')):
 try:ET.parse(f);check('Valid XML '+f.name,True)
 except Exception as e:check('Valid XML '+f.name,False);print(e)
rt=ET.parse(app/'MainWindow.xaml').getroot()
ns='{http://schemas.microsoft.com/winfx/2006/xaml}Name'
identifiers=[e.attrib[ns] for e in rt.iter() if ns in e.attrib]
check('Unique WPF names',len(identifiers)==len(set(identifiers)))
handlers=set(re.findall(r'\b(?:Click|SelectionChanged|SizeChanged|ValueChanged)="([A-Za-z_][A-Za-z_0-9]*)"',main))
check('All '+str(len(handlers))+' MainWindow event handlers defined', all(re.search(r'\b'+re.escape(h)+r'\s*\(',cs) for h in handlers))
for name in ['StatusLabel','GlassGpuToggleButton','GlassStrengthSlider','SessionElapsedText',
             'SampleRateText','ProcessedCountText','LostCountText','QuickInnerCommand','QuickOuterCommand',
             'QuickInnerAngleText','QuickOuterAngleText','QuickTableConnectionText',
             'QuickPositionMode','QuickMoveSpeed','PlotCaptionText','TopConnectionLamp',
             'RollText','PitchText','YawText','PlotCanvas','RollLine','PitchLine','DeviceVisual','ReferenceAxesVisual',
             'AbsoluteAngleButton','RelativeAngleButton','SetRelativeZeroButton',
             'ReferenceModeText','LogExpander','RunLog','TurntablePanel','MainTabs']:
 check('WPF field '+name,name in identifiers)
check('0/1 two-page navigation; no automatic test screen',len([e for e in rt.iter() if e.tag.endswith('}TabItem')])==2 and '自动测试' not in main)
check('GPU native HLSL preserved',(app/'Effects/LiquidGlass.hlsl').is_file() and (app/'Effects/LiquidGlassEffect.cs').is_file())
check('Glass control is ContentControl','sealed class LiquidGlassPane : ContentControl' in (app/'Controls/LiquidGlassPane.cs').read_text())
check('GLASS has realtime content, not a screenshot pasted as controls',main.count('<glass:LiquidGlassPane')>=8 and '<Viewport3D x:Name="AttitudeViewport"' in main and '<Polyline x:Name="RollLine"' in main)
check('Card backdrop is only abstract/decorative',len((app/'Assets/PrecisionAmbient.jpg').read_bytes())>1000)
check('Backdrop copied as WPF Resource','Resource Include="Assets/PrecisionAmbient.jpg"' in (app/'DynamicInclinometer.App.csproj').read_text())
check('Real data rate and counters',all(s in cs for s in ['Interlocked.Read(ref _processed)','Interlocked.Read(ref _lost)','SessionElapsedText.Text','SampleRateText.Text']))
check('No fake live numbers when disconnected','RollText.Text="--.---°"' in cs and 'PitchText.Text="--.---°"' in cs)
check('Dashboard quick movements are real controller delegates','MoveFromDashboardAsync(axis,command,QuickMoveSpeed.Text,IsQuickAbsolute)' in cs and 'return MoveAsync(axis,angle,speed,absolute);' in view)
check('Dashboard home requests current verified hardware flow','return HomeAxesAsync(new[]{0,2});' in view)
check('Dashboard stop sends real stop','StopFromDashboardAsync()' in view and 'await StopAllAndVerifyAsync()' in view)
check('Hardware stop is not falsely labeled as E-stop','双轴软件停车' in main and '实体急停' in view)
check('OpenGL/WebView not required','WebView' not in main and 'WebView' not in styles)
check('ABS/REL reference math preserved', 'TiltReferenceMath.RelativeTo' in cs)
check('Live plot can pause visually without stopping data','if(!_plotPaused)RenderPlot(roll,pitch);' in cs)
check('Connection buttons real','Connect_Click' in handlers and 'Stop_Click' in handlers)
check('Reference zero applied from actual attitude','Click="SetRelativeZero_Click"' in main and '_relativeZero = System.Numerics.Quaternion.Normalize' in cs)
check('Disallowed demo data not in XAML',not any(v in main for v in ['1.32°','125.6°','-0.86°','152,632','01:12:36','COM5','2.3 ms','200 Hz']))
check('XAML ResourceDictionary has no literal escaped newline',not any('\\n' in f.read_text(encoding='utf-8') for f in app.glob('*.xaml')))
for k in ['LiquidGlassCard','PrimaryAction','DangerAction','NavSelected','NavAction']:
 check('Shared style '+k,('x:Key="'+k+'"') in styles)
# Verify no code refs to removed circular gauge IDs.
check('Old gauge-only code fully removed','RollGaugeNeedle' not in cs and 'PitchGaugeNeedle' not in cs)
errors=[n for n,ok in checks if not ok]
print('STATIC DASHBOARD QA', len(checks)-len(errors),'/',len(checks))
if errors:sys.exit(1)
