"""自动运行状态相关"""
import threading


class AutoRunState:
    """自动运行状态相关"""

    def __init__(self):
        self.auto_run_state = "停止" # 停止、运行、错误
        self.auto_run_info = ""
        self.progress_bar_value = 0
        self.progress_info = ""

        self.thread_lock = threading.Lock()

        self.button_text_AccCalRun = "自动运行"


autoRunState = AutoRunState()
