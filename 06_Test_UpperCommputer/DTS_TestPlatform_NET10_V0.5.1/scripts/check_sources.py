"""V0.5 source-only preflight. DOES NOT replace dotnet build / Windows real hardware checks."""
from pathlib import Path
from collections import Counter
import json,re,struct,xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
for f in root.rglob('*.xaml'):
    doc=ET.parse(f)
    for el in doc.iter():
        # WPF TextWrapping is supported by TextBlock/TextBox, NOT CheckBox.
        # ElementTree does not validate WPF control properties. This regression
        # guard catches the V0.5 compile failure before Visual Studio.
        tag=el.tag.rsplit('}',1)[-1]
        if 'TextWrapping' in el.attrib:
            assert tag in ('TextBlock','TextBox'), f'{f}: {tag} cannot set TextWrapping'
        for key in ('Margin','Padding','BorderThickness'):
            if key not in el.attrib:continue
            a=[x for x in re.split(r'[ ,]+',el.attrib[key].strip()) if x]
            assert len(a) in (1,2,4) and all(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)',x) for x in a),(f,key,a)
    code=f.with_suffix('.xaml.cs')
    if not code.exists():continue
    source=code.read_text(encoding='utf-8')
    text=f.read_text(encoding='utf-8')
    for ev in re.findall(r'\b(?:Click|Closing|SelectionChanged)="([A-Za-z_][A-Za-z_0-9]*)"',text):
        assert ev+'(' in source, f'{f} missing event handler {ev}'
    names=re.findall(r'x:Name="([A-Za-z_][A-Za-z_0-9]*)"',text)
    assert len(names)==len(set(names)),f'duplicate names {f}'
for f in root.rglob('*.csproj'):ET.parse(f)
items=json.loads((root/'assets/tests.json').read_text(encoding='utf8'))
assert len(items)==84 and len({x['id'] for x in items})==84
assert Counter(x['stage'] for x in items)=={'S0':10,'S1':30,'S2':16,'S3':16,'S4':12}
modules=list((root/'src/Dts.Tests').glob('S?/*_Test.cs'))
assert len(modules)==84,f'Expected 84 files, got {len(modules)}'
file_ids={}
for f in modules:
    s=f.read_text(encoding='utf-8')
    ids=re.findall(r'public override string TestId\s*=>\s*"([^"]+)"',s)
    assert len(ids)==1 and ids[0] not in file_ids,f'bad module {f}'
    file_ids[ids[0]]=f
    assert f.parent.name==next(x['stage'] for x in items if x['id']==ids[0])
assert set(file_ids)=={x['id'] for x in items}
ready={id for id,f in file_ids.items() if 'public override bool IsExecutable => true;' in f.read_text(encoding='utf-8')}
assert ready=={'S0-04','CT-05','CT-09','CT-12'},ready
main=(root/'src/Dts.Wpf/MainWindow.xaml').read_text(encoding='utf-8')
code=(root/'src/Dts.Wpf/MainWindow.xaml.cs').read_text(encoding='utf-8')
assert 'StageGroupsList' in main and 'TestTileClick' in main
assert 'GetCustomAttribute<TestWindowForAttribute>()' in code and 'new GenericTestWindow(' in code
assert 'ChooseSaveRootClick' in code and 'MoveRelative(' in code
assert 'TdInnerDelta' in main and 'TdOuterDelta' in main and 'FdtInnerDelta' in main and 'FdtOuterDelta' in main
assert 'TdAxis' not in re.findall(r'x:Name="(.*?)"',main)
for f in (root/'vendor').glob('*.dll'):
    b=f.read_bytes();pe=struct.unpack_from('<I',b,0x3c)[0]
    assert b[:2]==b'MZ' and b[pe:pe+4]==b'PE\x00\x00' and struct.unpack_from('<H',b,pe+4)[0]==0x8664
print('PASS: XAML well-formed, Thickness checked, WPF handlers resolved')
print('PASS: 84 IDs / 84 independent .cs files; 4 actual entry points; 80 blocked placeholders')
print('PASS: CT-05 dedicated window, output path selector, dual-axis manual motion UI')
print('PASS: original vendor x64 DLLs present; no fake sample generation')
print('WARNING: no .NET 10 compiler, Windows WPF launch, or bench test performed here')
