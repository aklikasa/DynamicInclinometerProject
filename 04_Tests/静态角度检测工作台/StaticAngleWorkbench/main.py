"""静态角度工作台入口。Python 层异常写入持久日志；硬件 DLL 崩溃无法被 Python 保证捕获。"""
from __future__ import annotations
import faulthandler
import logging
import os
from pathlib import Path
import sys
import traceback
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from app.ui.main_window import MainWindow

LOG_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'StaticAngleLab' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'workbench_errors.log'
logging.basicConfig(filename=str(LOG_FILE), level=logging.ERROR,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
_fault_log = LOG_FILE.open('a', encoding='utf-8')
faulthandler.enable(file=_fault_log, all_threads=True)


def exception_hook(exc_type, exc, tb):
    detail = ''.join(traceback.format_exception(exc_type, exc, tb))
    logging.critical('未捕获的 Python 异常:\n%s', detail)
    try:
        QMessageBox.critical(None, '工作台异常（已保存错误日志）',
                             '程序捕获到异常，错误详情已保存到：\n' + str(LOG_FILE) +
                             '\n\n请检查转台实际状态。软件异常不代表电机已经停车。\n' +
                             str(exc))
    except Exception:
        pass


def main():
    sys.excepthook = exception_hook
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName('静态角度检测工作台')
    app.setOrganizationName('StaticAngleLab')
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.excepthook(*sys.exc_info())
        sys.exit(1)
