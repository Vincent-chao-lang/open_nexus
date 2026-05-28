"""
MCP 桥接器：封装本地文件操作（最小版本）。
不需要真实 MCP server，直接用 Python 文件操作替代。
"""
import os
from typing import Dict, Any, List


class MCPBridge:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.tools: List[Dict] = []

    async def initialize(self):
        """异步初始化（最小版本：直接返回）"""
        return self.tools

    def read_file(self, file_path: str) -> str:
        full_path = os.path.join(self.repo_path, file_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def write_file(self, file_path: str, content: str):
        full_path = os.path.join(self.repo_path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用本地工具（最小实现）"""
        if tool_name == "read_file":
            return self.read_file(arguments.get("path", ""))
        elif tool_name == "write_file":
            self.write_file(arguments.get("path", ""), arguments.get("content", ""))
            return {"status": "ok"}
        return {"status": "tool_not_found", "tool": tool_name}
