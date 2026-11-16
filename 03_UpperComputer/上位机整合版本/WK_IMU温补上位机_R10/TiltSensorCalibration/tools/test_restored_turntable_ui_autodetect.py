"""Offline-only tests for original motion controls and passive serial detection."""
from pathlib import Path
import sys
import ast
import xml.etree.ElementTree as ET
import types

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT/'ui/mainWindow.ui'
widgets={n.get('name') for n in ET.parse(ORIGINAL).iter('widget')}
required={'tab_27','tab_30','groupBox_InnerSstate','groupBox_OutState',
          'pushButton_InnerRun','pushButton_OutterRun','pushButton_InnerStop',
          'pushButton_OutterStop','pushButton_InnerReturnZero','pushButton_OutterReturnZero',
          'pushButton_InnerRunForSpeedMode','pushButton_OuterRunForSpeedMode',
          'pushButton_InnerRunForSwayMode','pushButton_OuterRunForSwayMode',
          'button_TurntableCommPortOpen'}
# For older revisions, tab_28 may be named differently, so match UI names programmatically.
missing=required-widgets
assert not missing, f'original UI controls unexpectedly missing: {missing}'
source=(ROOT/'form/form_turntable_ctrl.py').read_text(encoding='utf-8')
assert '_2fdt_diagnostic = QPlainTextEdit' not in source, 'old UI has been overlaid with a log pane'
assert '_2fdt_enable_button = QPushButton' in source
for name in ('_open_2fdt_checked','_enable_2fdt_axes','_close_2fdt_checked','_2td_pick_port_without_dialog'):
    assert f'def {name}(' in source
# ensure opening FDT doesn't route through old auto zero logic
branch=source[source.index("if combobox_text == '2FDT600WK':"):source.index('        # 调用 DLL 打开串口。',source.index("if combobox_text == '2FDT600WK':"))]
assert '_open_2fdt_checked()' in branch and 'return' in branch
sys.path.insert(0,str(ROOT/'turntable'))
from turntable_2fdt_autodetect import parse_frames, scan_axes

def frame(a, alarm, state, seq, angle):
    return f'${a}{alarm}{state}{seq:02d}{angle:08.4f}\r\n'.encode('ascii')
assert parse_frames(frame(1,0,1,5,123.1234))[0]==(1,0,1,123.1234)
assert parse_frames(b'nonsense') == []
assert parse_frames(frame(1,0,1,5,123.1234)[:-1]) == []
import turntable_2fdt_autodetect as module
module.list_ports=types.SimpleNamespace(comports=lambda: [types.SimpleNamespace(device=f'COM{i}') for i in (3,4,8,9)])
module.probe_port=lambda port,duration=0.8: (
    {1:{'count':4,'state':1,'alarm':0}} if port=='COM8'
    else {2:{'count':4,'state':1,'alarm':0}} if port=='COM9'
    else {},'synthetic read-only')
match,logs=scan_axes(('COM3','COM4'))
assert match=={1:'COM8',2:'COM9'}, match
# Duplicated signals cannot identify physical axis uniquely.
module.probe_port=lambda port,duration=0.8: ({1:{'count':4,'state':1,'alarm':0}},'test')
match, logs=scan_axes()
assert match=={},match
print('PASS: original motion UI retained, no diagnostic pane, passive COM8/COM9 mapping, ambiguous detection rejected')
