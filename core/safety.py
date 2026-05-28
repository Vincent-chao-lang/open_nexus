"""
安全围栏：Git 检查点、回滚与临时文件写入。
"""
import os
import subprocess
from typing import List


class SafetyNet:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.checkpoint_sha: str = ""
        self.temp_files: List[str] = []  # 记录本次任务创建的临时文件

    def _run_git(self, args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )

    def checkpoint(self, task_id: str):
        print(f"[Safety] 正在为任务 {task_id} 建立 Git 检查点...")
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path
            ).decode().strip()
            self.checkpoint_sha = sha
        except Exception:
            print("[Safety] 警告：无法获取 Git SHA，跳过检查点。")
        else:
            self._run_git(["add", "."])
            self._run_git(["stash", "push", "-m", f"nexus_pre_{task_id}"])
            self._run_git(["checkout", "-b", f"nexus/refactor-{task_id}"])
            self._run_git(["stash", "pop"])

    def commit(self, message: str):
        self._run_git(["add", "."])
        result = self._run_git(["commit", "-m", message])
        if result.returncode == 0:
            print(f"[Safety] 重构已提交: {message}")
        else:
            print(f"[Safety] 提交失败（可能无变更）: {result.stderr}")

    def rollback(self):
        print("[Safety] 正在强制回滚物理文件...")
        if self.checkpoint_sha:
            self._run_git(["reset", "--hard", self.checkpoint_sha])
        else:
            self._run_git(["reset", "--hard", "HEAD"])
        # 清理临时文件
        self._cleanup_temp_files()

    def write_temp_file(self, file_path: str, content: str):
        """
        写入临时文件（测试生成器等使用）。
        自动记录路径，以便 rollback 时清理。
        """
        full_path = os.path.join(self.repo_path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        self.temp_files.append(file_path)
        print(f"[Safety] 临时文件已写入: {file_path}")

    def _cleanup_temp_files(self):
        for tf in self.temp_files:
            full_path = os.path.join(self.repo_path, tf)
            if os.path.exists(full_path):
                os.remove(full_path)
        self.temp_files.clear()
