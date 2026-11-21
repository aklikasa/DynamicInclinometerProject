"""Qt-only equivalents for legacy tkinter messagebox/filedialog calls.

Used by the existing PySide6 GUI; no Tcl/Tk runtime is needed.
"""
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog


def _parent():
    app = QApplication.instance()
    return app.activeWindow() if app is not None else None


class messagebox:
    @staticmethod
    def showinfo(title, message, **kwargs):
        return QMessageBox.information(_parent(), str(title or "操作提示"), str(message))

    @staticmethod
    def showwarning(title, message, **kwargs):
        return QMessageBox.warning(_parent(), str(title or "操作提醒"), str(message))

    @staticmethod
    def showerror(title, message, **kwargs):
        return QMessageBox.critical(_parent(), str(title or "操作失败"), str(message))


class filedialog:
    @staticmethod
    def askdirectory(**kwargs):
        return QFileDialog.getExistingDirectory(
            _parent(), str(kwargs.get("title") or "选择文件夹"),
            str(kwargs.get("initialdir") or "")
        )
