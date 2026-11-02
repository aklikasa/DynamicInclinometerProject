"""Non-Windows STATIC validation only: NOT a substitute for dotnet build / hardware QA."""
from pathlib import Path
import xml.etree.ElementTree as ET
from pygments import lex
from pygments.lexers.dotnet import CSharpLexer
from pygments.token import Punctuation
import re, sys
root=Path(__file__).resolve().parents[1]
app=root/'src/DynamicInclinometer.App'
ui=(app/'MainWindow.xaml').read_text(encoding='utf-8')
cs=(app/'MainWindow.xaml.cs').read_text(encoding='utf-8')
passed=0
def check(label,v):
 global passed
 print(('PASS' if v else 'FAIL')+': '+label)
 if not v:sys.exit(1)
 passed+=1
for f in app.glob('*.xaml'):
 ET.parse(f); check('Well-formed XAML '+f.name,True)
r=ET.fromstring(ui)
names=[v for n in r.iter() for k,v in n.attrib.items() if k.endswith('}Name')]
check('Unique names',len(names)==len(set(names)))
check('GPU card removed and hidden advanced preferences remain', 'GPU 液态玻璃    Liquid Glass' not in ui and 'x:Name="GlassGpuToggleButton"' in ui and 'x:Name="GlassStrengthSlider"' in ui)
check('Two visible top-row cards', 'Grid.Column="2" Style="{StaticResource LiquidGlassCard}" Padding="13"' not in ui)
check('Independent connect/disconnect and record toggle handlers', 'Click="Connect_Click"' in ui and 'Click="Stop_Click"' in ui and '连接设备' in ui and '开始采集' in ui)
check('Monitoring does not create recorder', 'var recorder=ExperimentRecorder.Start' not in cs[cs.index('private void BeginCapture('):cs.index('private async Task RunPipeline(')])
check('Start recording creates one recorder', 'var recorder=ExperimentRecorder.Start' in cs[cs.index('private void StartManualRecording('):cs.index('private void FinishManualRecording(')])
check('Stop recording does not cancel source', 'StopCaptureAsync()' not in cs[cs.index('private void Stop_Click('):cs.index('private void OpenTurntableConsole_Click(')])
check('Recording thread synchronization', 'lock(_recordLock)' in cs and '_liveRecorder.Append(sample,state' in cs and '_liveRecorder.AppendDisplayed(sample' in cs)
check('Record auto-finalization at disconnect', 'FinishManualRecording("连接断开，采集记录自动收尾")' in cs)
check('Rolling measured processing rate distinct from hardware ODR', '_observedProcessingHz=(processed-_rateWindowCount)/windowSeconds;' in cs and '芯片 ODR 未读回' in cs)
check('Previously unverified 200Hz candidate not silently changed to 833Hz', 'x:Name="OdrInput" Text="200"' in ui and '硬件报告 833 Hz' in cs)
check('No unsupported literal newline in C# interpolation', 'OdrDisplayText.ToolTip=$"硬件工程师报告 ASM330LHHX 设置为 833 Hz，但当前没有芯片 ODR 寄存器读回。\n' not in cs)
check('Original calibration and ESKF present', '_engine.Update(sample,_cal!)' in cs and 'TiltReferenceMath.RelativeTo(' in cs)
check('Original turntable software stop and feedback present', 'QuickStopBoth_Click' in cs and 'OnTableFeedbackArrived' in cs)
for f in app.glob('*.xaml'):
 t=f.read_text(encoding='utf8')
 other=(app/(f.stem+'.xaml.cs')).read_text(encoding='utf8')
 for event in set(re.findall(r'\b(?:Click|SizeChanged|Closing|Loaded|ValueChanged)="([A-Za-z][A-Za-z0-9_]*)"',t)):
  check('Bound '+f.name+': '+event, bool(re.search(r'\b'+event+r'\s*\(',other)))
for f in [app/'MainWindow.xaml.cs']:
 depth=0;low=0
 for typ,val in lex(f.read_text(encoding='utf8'),CSharpLexer()):
  if typ in Punctuation:
   for ch in val:
    if ch=='{':depth+=1
    elif ch=='}':depth-=1;low=min(low,depth)
 check('C# bracket balance '+f.name,depth==0 and low>=0)
print(f'STATIC QA {passed}/{passed} passed (Windows compilation and real device NOT checked)')
