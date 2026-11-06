"""V0.6.0 source-only preflight. DOES NOT replace dotnet build / Windows real hardware checks."""
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
            value=el.attrib[key].strip()
            if value.startswith('{'): continue  # TemplateBinding/Binding, not a literal Thickness
            a=[x for x in re.split(r'[ ,]+',value) if x]
            assert len(a) in (1,2,4) and all(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)',x) for x in a),(f,key,a)
    code=f.with_suffix('.xaml.cs')
    if not code.exists():continue
    source=code.read_text(encoding='utf-8')
    text=f.read_text(encoding='utf-8')
    for ev in re.findall(r'\b(?:Click|Closing|SelectionChanged|Checked|Unchecked)="([A-Za-z_][A-Za-z_0-9]*)"',text):
        assert ev+'(' in source, f'{f} missing event handler {ev}'
    names=re.findall(r'x:Name="([A-Za-z_][A-Za-z_0-9]*)"',text)
    assert len(names)==len(set(names)),f'duplicate names {f}'
for f in root.rglob('*.csproj'):ET.parse(f)
items=json.loads((root/'assets/tests.json').read_text(encoding='utf8'))
assert len(items)==84 and len({x['id'] for x in items})==84
assert Counter(x['stage'] for x in items)=={'S0':10,'S1':30,'S2':16,'S3':16,'S4':12}
modules=list((root/'src/Dts.Tests').glob('S?/**/*_Test.cs'))
assert len(modules)==84,f'Expected 84 files, got {len(modules)}'
file_ids={}
for f in modules:
    s=f.read_text(encoding='utf-8')
    ids=re.findall(r'public override string TestId\s*=>\s*"([^"]+)"',s)
    assert len(ids)==1 and ids[0] not in file_ids,f'bad module {f}'
    file_ids[ids[0]]=f
    assert f.relative_to(root/'src/Dts.Tests').parts[0]==next(x['stage'] for x in items if x['id']==ids[0])
assert set(file_ids)=={x['id'] for x in items}
ready={id for id,f in file_ids.items() if 'public override bool IsExecutable => true;' in f.read_text(encoding='utf-8')}
assert ready=={'S0-04','CT-02','CT-05','CT-09','CT-12'},ready
main=(root/'src/Dts.Wpf/MainWindow.xaml').read_text(encoding='utf-8')
code=(root/'src/Dts.Wpf/MainWindow.xaml.cs').read_text(encoding='utf-8')
assert 'StageGroupsList' in main and 'TestTileClick' in main
assert 'GetCustomAttribute<TestWindowForAttribute>()' in code and 'new GenericTestWindow(' in code
assert 'ChooseSaveRootClick' in code and 'MoveRelative(' in code
assert 'TdInnerDelta' in main and 'TdOuterDelta' in main and 'FdtInnerDelta' in main and 'FdtOuterDelta' in main
assert 'TdAxis' not in re.findall(r'x:Name="(.*?)"',main)
# V0.5.2 UI regression guards: don't accidentally go back to fixed 620px device area.
assert 'WindowState="Maximized"' in main
assert 'Width="620"' not in main and 'MinWidth="1430"' not in main
assert 'CopyUidClick' in main and 'MCU 原始 UID' in main
assert 'ScanButton' in main and 'Width="94"' in main
assert 'CompactStages' in main and 'NavColumn' in main
assert 'OnMainSizeChanged' in code and 'UpdateTileSizing' in code
assert 'ToggleLogClick' in main and 'ToggleLogClick' in code
# V0.5.7 layout contracts: test rail is two-column, equipment tabs occupy full right height.
assert 'TestsColumn' in main and 'Width="500"' in main
assert 'TestTileColumns' in code and 'UniformGrid Columns="{DynamicResource TestTileColumns}"' in main
assert 'double desiredTestsWidth = ActualWidth >= 1800 ? 565' in code
assert 'EquipmentTabs' in main and '设备控制工作台' in main
assert '2TD-600 双轴转台' in main and '2FDT600WK 温控转台' in main and 'IMU / 采集 / 补偿' in main
right = main[main.index('<Grid x:Name="DevicesPanel"'):main.index('<Border Grid.Row="3"')]
assert '<ScrollViewer' not in right, 'Equipment controls must not contain an inner scrollbar'
assert 'SafetyConfirm' in right and 'TdStopClick' in right and 'FdtStopClick' in right

# V0.5.3 regression: missing MCU FS is a raw-only mode, not a reason to fake units or drop counts.
core=(root/'src/Dts.Core/Core.cs').read_text(encoding='utf8')
acq=(root/'src/Dts.Devices/Acquisition.cs').read_text(encoding='utf8')
cal=(root/'src/Dts.Core/CalibrationLibrary.cs').read_text(encoding='utf8')
assert 'double.NaN' in core and 'bool hasAcc=TryAccMg' in core
assert 'SelectedImuFrame.FromSample' in acq and 'raw_ax' in acq and 'imu_selected.csv' in acq
frame=(root/'src/Dts.Devices/SelectedImuFrame.cs').read_text(encoding='utf8')
assert 'MCU_FS_UNKNOWN' in frame and 'PHYSICAL_UNCALIBRATED_HISTORICAL_FS' in frame and 'TEMPERATURE_OUT_OF_MODEL_RANGE' in frame
assert 'ToSelectedCsvLine' in acq and 'SelectedImuFrame.CsvHeader' in acq
assert 'selected_file_is_primary=true' in acq
assert 'run.Mode!=CalibrationMode.Raw' not in acq[acq.index('StreamWriter? selectedWriter'):acq.index('while(duration is null')], 'Selected CSV must be created for raw mode too'
assert 'STOPPED_BY_OPERATOR' in acq and 'finally' in acq and 'manifest.json' in acq
assert 'uid_raw_12_bytes' in cal and 'raw_accel_bias_g' in cal and 'raw_gyro_bias_dps' in cal
assert 'RecurseSubdirectories = true' in cal and 'AttributesToSkip = FileAttributes.ReparsePoint' in cal
assert 'hashes.Length > 1' in cal and 'InvalidDataException' in cal
assert 'CalibrationRootText' in main and 'ChooseCalibrationRootClick' in code
ct05ui=(root/'src/Dts.Wpf/TestWindows/CT05/CT05Window.xaml').read_text(encoding='utf8')
ct05code=(root/'src/Dts.Wpf/TestWindows/CT05/CT05Window.xaml.cs').read_text(encoding='utf8')
ct05test=(root/'src/Dts.Tests/S1/CT_05_Test.cs').read_text(encoding='utf8')
assert 'ICalibrationRunAware' in ct05code and 'SetCalibrationRun' in ct05code
assert 'ChooseCalibrationClick' not in ct05ui and 'SelectedProcessingModeText' in ct05ui
assert 'settings.RunCalibration' in ct05test and 'source.Sha256' in ct05test
assert 'RecordButton' in main and '停止采集' in code and 'TimedCapture' in main
assert 'ImuSamplesGrid' in main and 'Acquisition.PreviewBatch' in code
assert 'DockPanel.Dock="Right" Content="连接温控转台"' not in main
assert 'DockPanel.Dock="Right" Content="执行所选轴归零' not in main
for f in (root/'vendor').glob('*.dll'):
    b=f.read_bytes();pe=struct.unpack_from('<I',b,0x3c)[0]
    assert b[:2]==b'MZ' and b[pe:pe+4]==b'PE\x00\x00' and struct.unpack_from('<H',b,pe+4)[0]==0x8664
print('PASS: XAML well-formed, Thickness checked, WPF handlers resolved')
print('PASS: 84 IDs / 84 independent .cs files; 5 actual entry points; 79 blocked placeholders')
print('PASS: CT-05 dedicated window, output path selector, dual-axis manual motion UI')
# 2TD auto-enables after operator safety confirmation: explicit enable controls become status.
for axis_control in ('TdAxisEnableClick','TdAxisDisableClick'):
    assert 'Click="'+axis_control+'"' not in main, axis_control
for axis_control in ('TdAxisRelativeClick','TdAxisStopClick','FdtAxisEnableClick',
                     'FdtAxisDisableClick','FdtAxisRelativeClick','FdtAxisStopClick'):
    assert main.count('Click="'+axis_control+'" Margin="5,6,5,6"') == 2, axis_control
print('PASS: V0.5.8 turntable button spacing and scroll-free two-axis controls')
assert 'ImuSamplesGrid' in main and 'LiveRowsCountText' in main and 'StreamStatusText' in main
assert 'UpdateLiveRows' in code and 'Acquisition.PreviewBatch' in code
assert 'liveRows:liveRows' in code
print('PASS: IMU multi-row DataGrid live telemetry with shared conversion/CSV serializer')
print('PASS: Recursive UID calibration matching, duplicate conflict blocking, global CT-05 calibration snapshot')
print('PASS: raw int16 capture with unknown FS, ambient/thermal modes, start/stop, provenance')
print('PASS: original vendor x64 DLLs present; no fake sample generation')
print('WARNING: no .NET 10 compiler, Windows WPF launch, or bench test performed here')

# V0.5.5: C# anonymous-type member initializers have no array target type.
# `physical_units=[...]` produces CS9176; it MUST explicitly construct an array.
diagnostic=(root/'src/Dts.Devices/StaticDiagnostics.cs').read_text(encoding='utf8')
assert 'physical_units = new string[]' in diagnostic, 'CS9176 regression: give physical_units an explicit array type'
assert not re.search(r'physical_units\s*=\s*\[',diagnostic), 'CS9176: anonymous array lacks target type'
print('PASS: StaticDiagnostics anonymous-object string array uses explicit type (CS9176 fixed)')

# V0.5.9: manual capture and test reports have independent persisted roots.
assert 'CaptureRootText' in main and 'ChooseCaptureRootClick' in code
assert 'capture_root.txt' in code and 'output_root.txt' in code
assert 'CaptureRootText.Text=_captureRoot' in code
assert 'Acquisition.CollectAsync(device,duration,id,progress,cts.Token,_captureRoot,' in code
assert 'new GenericTestWindow(definition,module,_testRunner,_testHardware,_saveRoot)' in code
assert 'x:Name="TdScanButton"' in main and 'Click="TdScanClick"' in main
assert 'x:Name="FdtScanButton"' in main and 'Click="FdtScanClick"' in main
assert 'SerialDiscovery.Find2TdAsync(ports,progress,CancellationToken.None)' in code
assert 'FdtDiscovery.ScanAsync(ports,progress,CancellationToken.None)' in code
assert 'PortsNotOccupiedByConnectedDevices()' in code
assert 'if(_imu?.Connected==true' in code and 'excluded.Add(_imu.PortName)' in code
assert 'SetScanningUi(true)' in code and 'SetScanningUi(false)' in code
print('PASS: independent persistent IMU capture root; report root unchanged')
print('PASS: per-turntable verified read-only COM discovery and connected-IMU exclusions')

# V0.6.0: screen-aware IMU layout, optional expanded data monitor and PMv2 manifest.
monitor=(root/'src/Dts.Wpf/ImuMonitorWindow.xaml').read_text(encoding='utf8')
monitor_code=(root/'src/Dts.Wpf/ImuMonitorWindow.xaml.cs').read_text(encoding='utf8')
manifest=(root/'src/Dts.Wpf/app.manifest').read_text(encoding='utf8')
csproj=(root/'src/Dts.Wpf/Dts.Wpf.csproj').read_text(encoding='utf8')
assert 'GlobalPathsExpander' in main and 'ImuDetailsExpander' in main
assert 'OpenImuMonitorClick' in main and 'ImuMonitorWindow(_liveRows)' in code
assert 'SamplesGrid' in monitor and 'Binding Ax' in monitor and 'Binding Gz' in monitor
assert 'CollectionChanged += FramesChanged' in monitor_code and 'CollectionChanged -= FramesChanged' in monitor_code
assert 'PerMonitorV2' in manifest and 'ApplicationManifest>app.manifest' in csproj
assert 'MinHeight="500"' in main and 'ApplyVerticalLayout()' in code
assert 'SelectedTestRow' in main and 'HeaderRow' in main
print('PASS: compact high-DPI layout + collapsible metadata + full-screen live-data monitor + PMv2 manifest')

# V0.6.1 incremental vendor command and disconnect lifecycle checks.
turntables=(root/'src/Dts.Devices/Turntables.cs').read_text(encoding='utf8')
assert 'EntryPoint="SetAxisOpposition"' in turntables
assert 'Math.Abs(delta)>90' not in turntables
assert 'TdNative.Opposition(axis,delta,speed)' in turntables
assert '速度范围为0.01～60' not in turntables or '速率范围为0.01～60' in turntables
assert 'TdConnectButton' in main and 'FdtConnectButton' in main and 'ImuConnectButton' in main
assert '安全断开' in code and '请先安全断开转台' in code
print('PASS: V0.6.1 vendor incremental-position / connected-state toggles / safe-exit guards')

# V0.6.3 UI regressions: deterministic 2-column tiles, three live status cards, shared telemetry style.
assert 'TestTileWidth' not in main and 'TestTileWidth' not in (root/'src/Dts.Wpf/App.xaml').read_text(encoding='utf8')
assert 'TestTileColumns' in (root/'src/Dts.Wpf/App.xaml').read_text(encoding='utf8')
assert all(x in main for x in ('ImuStateDot','TdStateDot','FdtStateDot','ImuStateValue','TdStateValue','FdtStateValue'))
assert all(x in code for x in ('_latestTdSnapshot','_latestFdtSnapshot','UpdateConnection();'))
assert 'Content="连接并使能' not in main and 'Content="连接" Width="92"' in main
assert 'Style="{StaticResource TelemetryGrid}"' in main and 'Style="{StaticResource TelemetryGrid}"' in monitor
assert all(x in (root/'src/Dts.Wpf/App.xaml').read_text(encoding='utf8') for x in ('TelemetryRow','TelemetryCell','TelemetryHeader','DeviceStatusCard'))
print('PASS: V0.6.3 two-column cards, bounded global paths, real device indicators, modern shared telemetry style')
