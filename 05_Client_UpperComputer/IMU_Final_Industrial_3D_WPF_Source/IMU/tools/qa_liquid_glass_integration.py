#!/usr/bin/env python3
"""Dependency-free SOURCE inspection; does NOT compile Windows WPF or run devices."""
from pathlib import Path
from collections import Counter
import hashlib, re, sys, xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
app=root/"src"/"DynamicInclinometer.App"
checks=[]
def check(name,ok):
    checks.append((name,bool(ok)))
    print(("PASS" if ok else "FAIL")+": "+name)

for path in sorted(list(root.rglob("*.xaml"))+list(root.rglob("*.csproj"))):
    try:ET.parse(path);check("valid XML: "+str(path.relative_to(root)),True)
    except Exception as e:check("valid XML: "+str(path.relative_to(root)),False);print(e)
# WPF App.Resources is a ResourceDictionary. Pure ElementTree XML syntax checks
# are insufficient: non-whitespace text nodes are illegal dictionary entries.
XAML_NS="http://schemas.microsoft.com/winfx/2006/xaml"
WPF_NS="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
for path in root.rglob("*.xaml"):
    tree=ET.parse(path)
    for element in tree.iter():
        tag=element.tag.split("}")[-1] if isinstance(element.tag,str) else ""
        if tag in ("Application.Resources","Window.Resources","ResourceDictionary","UserControl.Resources"):
            check(str(path.relative_to(root))+": no non-whitespace dictionary heading",not bool((element.text or "").strip()))
            for item in element:
                check(str(path.relative_to(root))+": dictionary child has no stray text after it",not bool((item.tail or "").strip()))
                if isinstance(item.tag,str) and not item.tag.endswith("}ResourceDictionary.MergedDictionaries"):
                    legal=("{"+XAML_NS+"}Key") in item.attrib or item.tag.endswith("}Style") or item.tag.endswith("}ControlTemplate") or item.tag.endswith("}DataTemplate")
                    # Implicit WPF styles are legal without explicit x:Key when TargetType exists.
                    if item.tag.endswith("}Style") and not ("{"+XAML_NS+"}Key") in item.attrib:
                        legal="TargetType" in item.attrib
                    check(str(path.relative_to(root))+": ResourceDictionary entry has a key or supported implicit key",legal)
# Verify the clr-namespace prefix really matches the shipped C# ContentControl.
app_xaml=(app/"App.xaml").read_text(encoding="utf-8")
control_cs=(app/"Controls/LiquidGlassPane.cs").read_text(encoding="utf-8")
check("glass CLR namespace resolves from App.xaml", 'xmlns:glass="clr-namespace:DynamicInclinometer.App.Controls"' in app_xaml and 'namespace DynamicInclinometer.App.Controls;' in control_cs and 'class LiquidGlassPane : ContentControl' in control_cs)
check("glass control type in App.xaml matches shipped class", '{x:Type glass:LiquidGlassPane}' in app_xaml)
check("no literal escaped backslash-n in any XAML", not any('\\n' in f.read_text(encoding="utf-8") for f in root.rglob('*.xaml')))
main=(app/"MainWindow.xaml").read_text(encoding="utf-8")
manual=(app/"TurntableControlView.xaml").read_text(encoding="utf-8")
main_cs=(app/"MainWindow.xaml.cs").read_text(encoding="utf-8")
manual_cs=(app/"TurntableControlView.xaml.cs").read_text(encoding="utf-8")
for name,xaml,code in (("MainWindow",main,main_cs),("TurntableControlView",manual,manual_cs)):
    names=re.findall(r'x:Name="([^"]+)"',xaml)
    check(name+" unique names",max(Counter(names).values(),default=0)==1)
    handlers=set(re.findall(r'\b(?:Click|Checked|Unchecked|ValueChanged|SelectionChanged|SizeChanged|Loaded)="([A-Za-z_]\w*)"',xaml))
    check(name+" handlers present",all(re.search(r'\b'+re.escape(h)+r'\s*\(',code) for h in handlers))
    check(name+" uses GPU glass panes","<glass:LiquidGlassPane" in xaml)
check("no automatic test tab", 'Header="   自动测试' not in main)
check("real-time monitor tab retained", 'Header="实时监测"' in main)
check("manual control tab retained", 'Header="转台手动控制"' in main)
check("no main-page auto-test buttons", 'Click="RealAutoRun_Click"' not in main)
check("legacy auto handler disabled", "_automaticTestingRemoved" in main_cs)
check("ABS and REL retained",all(n in main for n in ("AbsoluteAngleButton","RelativeAngleButton","SetRelativeZeroButton","ReferenceModeText")))
check("shader code retained",(app/"Effects/LiquidGlass.hlsl").is_file())
check("in-process D3D9 shader compiler present",(app/"Effects/RuntimeShaderCompiler.cs").is_file())
check("WinExe AppHost enabled","<UseAppHost>true</UseAppHost>" in (app/"DynamicInclinometer.App.csproj").read_text())
check("HLSL embedded and no nested shader build",'EmbeddedResource Include="Effects/LiquidGlass.hlsl"' in (app/"DynamicInclinometer.App.csproj").read_text() and "CompileLiquidGlassShader" not in (app/"DynamicInclinometer.App.csproj").read_text())
check("pixel shader bytecode loaded from MemoryStream","pixelShader.SetStreamSource(bytes)" in (app/"Effects/LiquidGlassEffect.cs").read_text())
check("content control avoids old namescope bug","LiquidGlassPane : ContentControl" in (app/"Controls/LiquidGlassPane.cs").read_text())
check("background without huge LIQUID/GLASS words",not re.search(r'Text="(?:LIQUID|GLASS|LIQUID GLASS)"',main))
check("GPU toggle & strength slider",all(n in main for n in ("GlassGpuToggleButton","GlassStrengthSlider")))
check("retained 2TD-600 axis control",all(n in manual for n in ("MoveBoth_Click","HomeBoth_Click","Stop_Click")))
check("preserved recording files","display_processed.csv" in (root/"src/DynamicInclinometer.Infrastructure/ExperimentRecorder.cs").read_text())
print(f"\\nSTATIC CHECKS: {sum(1 for _,ok in checks if ok)}/{len(checks)} passed")
sys.exit(1 if any(not ok for _,ok in checks) else 0)
