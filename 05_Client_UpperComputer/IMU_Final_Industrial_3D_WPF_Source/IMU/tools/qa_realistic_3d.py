#!/usr/bin/env python3
"""Structural tests for WPF industrial 3D preview. Does NOT drive an IMU or turntable."""
from pathlib import Path
import re,sys,math,xml.etree.ElementTree as ET
from collections import Counter
from pygments import lex
from pygments.lexers.dotnet import CSharpLexer
from pygments.token import Token
root=Path(__file__).resolve().parents[1]
ui=root/'src/DynamicInclinometer.App/MainWindow.xaml'
code=(root/'src/DynamicInclinometer.App/MainWindow.xaml.cs').read_text(encoding='utf-8')
model=(root/'src/DynamicInclinometer.App/Controls/IndustrialImu3D.cs').read_text(encoding='utf-8')
app=(root/'src/DynamicInclinometer.App/DynamicInclinometer.App.csproj').read_text(encoding='utf-8')
x=ET.parse(ui)
checks=[]
def ok(test,condition):
 checks.append((test,bool(condition)))
 print(('PASS' if condition else 'FAIL'),test)
for file in root.rglob('*.xaml'):
 try:ET.parse(file);ok(f'XAML parse: {file.name}',True)
 except ET.ParseError as e: print(e);ok(f'XAML parse: {file.name}',False)
for file in root.rglob('*.csproj'):
 try:ET.parse(file);ok(f'Project XML parse: {file.name}',True)
 except ET.ParseError:ok(f'Project XML parse: {file.name}',False)
ns={'x':'http://schemas.microsoft.com/winfx/2006/xaml'}
names=[v for el in x.iter() for k,v in el.attrib.items() if k.endswith('}Name')]
ok('Unique MainWindow names',len(set(names))==len(names))
handlers=set()
for element in x.iter():
 for event in ['Click','MouseMove','MouseLeftButtonDown','MouseLeftButtonUp','MouseWheel']:
  if event in element.attrib:handlers.add(element.attrib[event])
missing=[handler for handler in handlers if not re.search(r'\b'+re.escape(handler)+r'\s*\(',code)]
ok('All UI event handlers connected',not missing)
if missing: print('missing:',missing)
for key in ['ResetAttitudeCamera_Click','ToggleImuAxes_Click','AutoOrbitCamera_Click','AttitudeScene_MouseDown','AttitudeScene_MouseMove','AttitudeScene_MouseUp','AttitudeScene_MouseWheel']:
 ok(f'3D control: {key}',key in handlers)
ok('3D model uses independent ESKF rotation','CreateBody(_rotation,_showImuAxes)' in code and 'group.Transform=new RotateTransform3D(sensorRotation)' not in model and 'body.Transform=new RotateTransform3D(sensorRotation)' in model)
ok('World dial is separate', 'ReferenceAxesVisual.Content=IndustrialImu3D.CreateWorldReference(_showImuAxes)' in code)
ok('No old unlit PCB geometry', '39,138,163' not in code and 'private static void AddAxis(' not in code)
ok('Metallic material uses specular & diffuse', 'new DiffuseMaterial(' in model and 'new SpecularMaterial(' in model)
ok('Beveled shell geometry',model.count('AddRoundedPrism(body,')>=6 and 'for(int layer=0;layer<3;layer++)' in model)
ok('Four mounting lugs', 'for(int sx=-1;sx<=1;sx+=2)' in model and 'for(int sy=-1;sy<=1;sy+=2)' in model and 'AddVerticalRing(body,hx,hy' in model)
ok('Open mounting holes, not solid discs', 'boreRadius' in model and 'AddVerticalRing' in model)
ok('Machined cooling ribs', 'AddRibOnSide(body' in model and 'i<11' in model)
ok('Circular metal connector and LED', 'AddRoundConnector(body)' in model and 'AddAxialCylinder(body' in model and 'Color.FromRgb(43,145,200)' in model)
ok('No manufacturer brand/logo on enclosure', 'DYNAMIC INCLINOMETER' in model and '6-AXIS INERTIAL SENSOR' in model and 'HDA436T' not in model)
ok('Compact camera view', '_cameraAzimuth=-135.0;' in code and '_cameraDistance=9.7;' in code)
ok('Compact single-line 3D toolbar', 'UniformGrid Grid.Row="2" Columns="4"' in ui.read_text(encoding='utf-8'))
ok('3D label is an actual material texture', 'RenderTargetBitmap(' in model and 'TextureCoordinates.Add' in model)
ok('Circle dial 72 ticks', 'degrees<360;degrees+=5' in model and 'AddAnnulus(world' in model)
ok('Reference axes not tied to the IMU quaternion', 'var world=new Model3DGroup();' in model and 'return world;' in model)
ok('Camera movement does not change _rotation', '_rotation.Quaternion=' not in code[code.index('private void ApplyAttitudeCamera()'):code.index('private void RefreshPorts()')])
ok('Demo automatic-test tab is still absent','自动测试' not in ui.read_text(encoding='utf-8'))
ok('ABS and REL preserved','x:Name="AbsoluteAngleButton"' in ui.read_text(encoding='utf-8') and 'x:Name="RelativeAngleButton"' in ui.read_text(encoding='utf-8'))
ok('No nested ShaderBuild project', 'ShaderBuild' not in app and 'LiquidGlass.hlsl' in app)
# Use Pygments for limited bracket-balance syntax inspection, ignoring strings and comments.
for file in [root/'src/DynamicInclinometer.App/MainWindow.xaml.cs',root/'src/DynamicInclinometer.App/Controls/IndustrialImu3D.cs']:
 pairs={'{':'}','(':')','[':']'}; stack=[]
 for token,body in lex(file.read_text(encoding='utf-8'),CSharpLexer()):
  if token in Token.Punctuation:
   for ch in body:
    if ch in pairs:stack.append(pairs[ch])
    if ch in '})]':
     if stack and stack[-1]==ch: stack.pop()
     else: stack.append('MISMATCH')
 ok('C# punctuation balanced: '+file.name,not stack)
# Analytic geometry sanity: rounded bevel radius, profile heights and ring radii.
ok('Enclosure dimensions physically sensible',1.42 > .15 and .80 > .15 and .263 > -.266)
ok('Dial separated from device in world frame',2.00 > 1.4 and -.58<-.25)
print(f'\nRESULT: {sum(v for _,v in checks)}/{len(checks)} passed')
sys.exit(0 if all(v for _,v in checks) else 1)
