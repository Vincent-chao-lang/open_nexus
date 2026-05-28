"""
代码分析器：通过 AST 静态分析代码结构和依赖关系。
"""
import os
import ast
import re
from typing import List, Dict, Any, Tuple, Set


def file_to_module(repo_path: str, file_path: str) -> str:
    """将文件路径转换为 Python 模块名。"""
    rel = os.path.relpath(file_path, repo_path)
    no_ext = rel.replace(".py", "").replace("/", ".").replace("\\", ".")
    no_ext = re.sub(r'\.?__init__$', '', no_ext)
    return no_ext


class CodeAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    # ---- 内部工具：模块名解析 ----

    def _file_to_module(self, file_path: str) -> str:
        return file_to_module(self.repo_path, file_path)

    def _resolve_relative_import(
        self, current_file: str, import_spec: str, level: int
    ) -> str:
        current_module = self._file_to_module(current_file)
        parts = current_module.split(".")
        if level > len(parts):
            return ""
        base = ".".join(parts[: len(parts) - level + 1])
        return f"{base}.{import_spec}" if import_spec else base

    def _extract_imports(self, file_path: str) -> Set[str]:
        full_path = os.path.join(self.repo_path, file_path)
        if not os.path.exists(full_path):
            return set()

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except SyntaxError:
            return set()

        imports: Set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                level = node.level or 0
                if level > 0:
                    resolved = self._resolve_relative_import(
                        file_path, node.module, level
                    )
                    if resolved:
                        imports.add(resolved)
                else:
                    imports.add(node.module)

        return imports

    def map_dependencies(self, target_files: List[str]) -> Dict[str, Any]:
        target_modules: Set[str] = set()
        for tf in target_files:
            target_modules.add(self._file_to_module(tf))

        inbound_nodes: List[str] = []
        outbound_nodes: List[str] = []

        for tf in target_files:
            for imp in self._extract_imports(tf):
                if self._is_project_module(imp):
                    outbound_nodes.append(imp)

        for root, _, files in os.walk(self.repo_path):
            if any(skip in root for skip in ['venv', '.git', '__pycache__', 'node_modules', '.tox', 'data', '.claude']):
                continue
            for file in files:
                if not file.endswith(".py"):
                    continue
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.repo_path)
                if rel_path in target_files:
                    continue

                imported_modules = self._extract_imports(rel_path)
                for target_mod in target_modules:
                    if self._module_matches(target_mod, imported_modules):
                        inbound_nodes.append(rel_path)
                        break

        return {
            "target": target_files,
            "target_modules": list(target_modules),
            "inbound": list(set(inbound_nodes)),
            "outbound": list(set(outbound_nodes))
        }

    def _is_project_module(self, module_name: str) -> bool:
        path_parts = module_name.split(".")
        as_file = os.path.join(self.repo_path, *path_parts) + ".py"
        as_pkg = os.path.join(self.repo_path, *path_parts, "__init__.py")
        return os.path.exists(as_file) or os.path.exists(as_pkg)

    def _module_matches(self, target_module: str, imported: Set[str]) -> bool:
        for imp in imported:
            if imp == target_module:
                return True
            if imp.startswith(target_module + "."):
                return True
        return False

    def get_signatures(self, file_path: str) -> str:
        full_path = os.path.join(self.repo_path, file_path)
        if not os.path.exists(full_path):
            return ""
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
            signatures = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [arg.arg for arg in node.args.args]
                    signatures.append(f"def {node.name}({', '.join(args)})")
                elif isinstance(node, ast.ClassDef):
                    bases = [getattr(b, 'id', '') for b in node.bases if hasattr(b, 'id')]
                    base_str = f"({', '.join(bases)})" if bases else ""
                    signatures.append(f"class {node.name}{base_str}")
            return "\n".join(signatures)
        except Exception:
            return "无法解析该文件结构"

    def local_static_check(self, code: str) -> Tuple[bool, str]:
        try:
            ast.parse(code)
            return True, "Syntax OK"
        except SyntaxError as e:
            return False, f"Syntax Error: {e.msg} at line {e.lineno}"
