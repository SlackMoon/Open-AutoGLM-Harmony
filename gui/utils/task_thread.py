"""Own a task runner until its background execution has actually returned."""

import logging

from PyQt5.QtCore import QThread


class AgentTaskThread(QThread):
    def __init__(self, runner, task, parent=None):
        super().__init__(parent)
        self.runner = runner
        self.task = task
        runner.moveToThread(self)
        self.finished.connect(runner.deleteLater)

    def run(self):
        try:
            self.runner.run_task(self.task)
        except Exception as exc:
            logging.exception("Task worker failed")
            self.runner.error_occurred.emit(f"任务执行出错: {exc}")
        finally:
            agent = self.runner._agent
            if agent is not None:
                try:
                    agent.model_client.client.close()
                except Exception:
                    logging.exception("Could not close model connection")
