"""
上下文新鲜度管理器：检测存储的索引是否过期。
（最小版本：基于 Git SHA 的简单检测）
"""
import subprocess
from typing import Dict


class FreshnessManager:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.index_versions: Dict[str, str] = {}
        self.stale_markers: Dict[str, bool] = {}

    def get_current_head(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True, text=True
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    def mark_stale(self, file_path: str):
        self.stale_markers[file_path] = True

    def check(self, file_path: str) -> Dict[str, object]:
        current_head = self.get_current_head()
        indexed_sha = self.index_versions.get(file_path, "")

        is_stale = (
            self.stale_markers.get(file_path, False)
            or indexed_sha != current_head
        )

        if is_stale and file_path in self.stale_markers:
            del self.stale_markers[file_path]

        return {
            "file": file_path,
            "indexed_at": indexed_sha[:8] if indexed_sha else "never",
            "current_head": current_head[:8],
            "is_stale": is_stale
        }
