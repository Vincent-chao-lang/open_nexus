"""
项目扫描器：对目标项目做全局"体检"，输出重构建议、优先级和影响范围。
这是大型项目重构的第一步——先搞清楚问题全貌，再决定从哪里动刀。
"""
import os
import ast
from typing import Dict, List, Tuple


def collect_python_files(repo_path: str) -> List[str]:
    """扫描仓库中所有 Python 文件，跳过无关目录和测试文件。"""
    skip = {'__pycache__', 'venv', '.git', '.venv', 'node_modules',
            '.tox', '.mypy_cache', '.pytest_cache', 'dist', 'build',
            '.claude', '.idea', '.vscode', 'tests', 'test', 'data'}
    result = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith('.py') and not f.startswith('test_'):
                rel = os.path.relpath(os.path.join(root, f), repo_path)
                result.append(rel)
    return sorted(result)


class ProjectScanner:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def full_scan(self) -> Dict:
        """
        全项目扫描，返回体检报告：
        {
          "project": "...",
          "total_files": 42,
          "total_functions": 156,
          "issues": { "critical": [...], "warning": [...], "info": [...] },
          "dependency_graph": { "module_a": ["module_b", ...], ... },
          "refactoring_roadmap": [
            {"phase": 1, "reason": "底层依赖，无上游，先重构", "files": [...]},
            ...
          ]
        }
        """
        all_files = self._collect_python_files()
        issues = self._analyze_all_files(all_files)
        dep_graph = self.build_dependency_graph(all_files)
        roadmap = self._build_roadmap(issues, dep_graph)

        return {
            "project": os.path.basename(os.path.abspath(self.repo_path)),
            "total_files": len(all_files),
            "issues": issues,
            "dependency_graph_summary": {
                k: list(v)[:5] for k, v in dep_graph.items()
            },
            "refactoring_roadmap": roadmap
        }

    def _collect_python_files(self) -> List[str]:
        return collect_python_files(self.repo_path)

    def _analyze_all_files(self, all_files: List[str]) -> Dict[str, List[Dict]]:
        critical, warning, info = [], [], []

        for file_path in all_files:
            full = os.path.join(self.repo_path, file_path)
            try:
                with open(full, "r", encoding="utf-8") as f:
                    code = f.read()
                tree = ast.parse(code)
            except Exception:
                continue

            lines = code.split('\n')
            file_issues = self._scan_file(file_path, tree, lines)
            critical.extend(file_issues.get("critical", []))
            warning.extend(file_issues.get("warning", []))
            info.extend(file_issues.get("info", []))

        return {"critical": critical, "warning": warning, "info": info}

    def _scan_file(self, file_path: str, tree: ast.AST, lines: List[str]) -> Dict:
        critical, warning, info = [], [], []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                issues = self._analyze_function(node, lines, file_path)
                for severity, msg in issues:
                    item = {
                        "file": file_path,
                        "function": node.name,
                        "line": node.lineno,
                        "message": msg
                    }
                    if severity == "critical":
                        critical.append(item)
                    elif severity == "warning":
                        warning.append(item)
                    else:
                        info.append(item)

            elif isinstance(node, ast.ClassDef):
                issues = self._analyze_class(node, file_path)
                for severity, msg in issues:
                    item = {
                        "file": file_path,
                        "class": node.name,
                        "line": node.lineno,
                        "message": msg
                    }
                    if severity == "critical":
                        critical.append(item)
                    elif severity == "warning":
                        warning.append(item)
                    else:
                        info.append(item)

        return {"critical": critical, "warning": warning, "info": info}

    def _analyze_function(
        self, node: ast.FunctionDef, lines: List[str], file_path: str
    ) -> List[Tuple[str, str]]:
        issues = []
        func_lines = node.end_lineno - node.lineno if node.end_lineno else 0

        # 长函数检测
        if func_lines > 80:
            issues.append((
                "critical",
                f"长函数 ({func_lines} 行) — 强烈建议拆分为 3-5 个小函数"
            ))
        elif func_lines > 40:
            issues.append((
                "warning",
                f"中等长度函数 ({func_lines} 行) — 考虑提取子逻辑"
            ))

        # 参数过多
        arg_count = len(node.args.args)
        if arg_count > 5:
            issues.append((
                "warning",
                f"参数过多 ({arg_count} 个) — 考虑封装为数据类或配置对象"
            ))

        # 嵌套过深
        max_depth = self._max_nesting(node)
        if max_depth > 4:
            issues.append((
                "warning",
                f"嵌套深度 {max_depth} — 建议提取内层逻辑或使用提前返回"
            ))

        # 缺少类型注解
        has_return_annotation = node.returns is not None
        has_arg_annotations = any(a.annotation for a in node.args.args)
        if not has_return_annotation and not has_arg_annotations:
            if func_lines > 15:
                issues.append((
                    "info",
                    "缺少类型注解 — 建议添加参数和返回值类型"
                ))

        # 检测可能的副作用混合（同时有 IO 和计算逻辑的迹象）
        io_keywords = {'open(', 'print(', 'requests.', 'http.', 'urllib.',
                       'send_email', 'send_message', 'write(', 'read(',
                       'execute(', 'commit()', 'cursor.', 'sleep('}
        has_io = any(kw in self._get_func_body(node, lines) for kw in io_keywords)
        has_business_logic = func_lines > 20  # 简化判断
        if has_io and has_business_logic:
            issues.append((
                "warning",
                "混合了 IO 操作和业务逻辑 — 建议分离为纯函数 + IO 层"
            ))

        return issues

    def _analyze_class(self, node: ast.ClassDef, file_path: str) -> List[Tuple[str, str]]:
        issues = []
        method_count = sum(
            1 for n in ast.walk(node)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

        if method_count > 12:
            issues.append((
                "critical",
                f"大类 ({method_count} 个方法) — 职责可能过重，建议按职责拆分"
            ))
        elif method_count > 7:
            issues.append((
                "warning",
                f"方法数较多 ({method_count} 个) — 检查是否违反单一职责原则"
            ))

        # 检查 __init__ 中是否注入了过多依赖
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef) and child.name == '__init__':
                init_args = [a for a in child.args.args if a.arg != 'self']
                if len(init_args) > 5:
                    issues.append((
                        "warning",
                        f"构造函数依赖过多 ({len(init_args)} 个) — 考虑引入依赖注入容器"
                    ))

        return issues

    def _max_nesting(self, node: ast.AST, current: int = 0) -> int:
        max_depth = current
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try,
                                   ast.With, ast.AsyncWith, ast.AsyncFor)):
                depth = self._max_nesting(child, current + 1)
                max_depth = max(max_depth, depth)
            else:
                depth = self._max_nesting(child, current)
                max_depth = max(max_depth, depth)
        return max_depth

    def _get_func_body(self, node: ast.FunctionDef, lines: List[str]) -> str:
        if node.end_lineno:
            return '\n'.join(lines[node.lineno - 1:node.end_lineno])
        return ""

    def build_dependency_graph(self, all_files: List[str]) -> Dict[str, set]:
        """构建项目级依赖图"""
        graph: Dict[str, set] = {}
        for f in all_files:
            graph[f] = set()

        for f in all_files:
            full = os.path.join(self.repo_path, f)
            try:
                with open(full, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        dep_file = self._module_to_file(alias.name)
                        if dep_file and dep_file in all_files and dep_file != f:
                            graph[f].add(dep_file)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.level == 0:
                        dep_file = self._module_to_file(node.module)
                        if dep_file and dep_file in all_files and dep_file != f:
                            graph[f].add(dep_file)

        return graph

    def _module_to_file(self, module_name: str) -> str:
        parts = module_name.split('.')
        as_file = os.path.join(*parts) + '.py'
        as_pkg = os.path.join(*parts, '__init__.py')
        if os.path.exists(os.path.join(self.repo_path, as_file)):
            return as_file
        if os.path.exists(os.path.join(self.repo_path, as_pkg)):
            return os.path.join(*parts, '__init__.py')
        return ""

    def _build_roadmap(self, issues: Dict, dep_graph: Dict[str, set]) -> List[Dict]:
        """
        根据依赖关系和问题严重程度规划重构顺序：
        - Phase 1: 被依赖最多 + 有 Critical 问题的文件（底层模块，先修）
        - Phase 2: 有 Warning 的文件
        - Phase 3: 入口/路由文件（最上层，最后修）
        """
        # 计算每个文件被多少其他文件依赖
        dependents: Dict[str, int] = {f: 0 for f in dep_graph}
        for f, deps in dep_graph.items():
            for d in deps:
                if d in dependents:
                    dependents[d] += 1

        # 找出有问题的文件
        problem_files: Dict[str, str] = {}  # file → 最高严重级别
        for severity in ["critical", "warning"]:
            for issue in issues.get(severity, []):
                f = issue["file"]
                if f not in problem_files or severity == "critical":
                    problem_files[f] = severity

        # 排序：被依赖多 + 有严重问题 → 优先
        scored = []
        for f, severity in problem_files.items():
            score = dependents.get(f, 0) * 10
            if severity == "critical":
                score += 100
            elif severity == "warning":
                score += 50
            scored.append((score, f, severity))

        scored.sort(reverse=True)

        if not scored:
            return [{"phase": 0, "reason": "未发现需要重构的问题", "files": []}]

        # 分成 3 个阶段
        chunk_size = max(1, len(scored) // 3)
        phases = []
        for i in range(3):
            chunk = scored[i * chunk_size:(i + 1) * chunk_size]
            if not chunk:
                break
            if i == 0:
                reason = "底层依赖 + 严重问题 — 最优先修复，影响面最大"
            elif i == 1:
                reason = "中等优先级 — 被依赖较少或问题较轻"
            else:
                reason = "上层入口/叶子模块 — 最后处理，避免接口变更影响下游"

            phases.append({
                "phase": i + 1,
                "reason": reason,
                "files": [
                    {"file": f[1], "severity": f[2], "dependents": dependents.get(f[1], 0)}
                    for f in chunk
                ]
            })

        return phases
