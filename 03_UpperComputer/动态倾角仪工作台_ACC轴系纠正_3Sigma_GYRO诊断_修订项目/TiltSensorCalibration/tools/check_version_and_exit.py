"""检查正在使用的源码版本和退出保护，不依赖 PySide6、硬件。"""
from pathlib import Path
import ast
import hashlib
root=Path(__file__).resolve().parents[1]
m=(root/'main.py').read_text(encoding='utf-8-sig')
f=(root/'form/form_turntable_ctrl.py').read_text(encoding='utf-8-sig')
assert not ('sys.excepthook' in m), '当前 main.py 含新版全局异常弹窗，请检查 PyCharm 路径'
assert 'QCoreApplication.quit()' in f, '退出修订尚未生效'
assert 'while True:' not in f[f.index('def pushButton_closeWindows_Click'):f.index('def widget_visible_set')], '退出函数存在无限等待'
ast.parse(m);ast.parse(f)
print('项目路径：',root)
print('Python 主程序 SHA256：', hashlib.sha256((root/'main.py').read_bytes()).hexdigest())
print('PASS：旧版 main.py 没有全局异常弹窗；已启用退出防无限等待逻辑')
