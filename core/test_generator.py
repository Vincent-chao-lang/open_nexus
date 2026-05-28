"""
测试自动生成器：为目标代码生成 happy-path 测试桩。
"""
import os
import ast
import re
from typing import Dict, List, Optional, Tuple


class TestGenerator:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def find_existing_tests(self, target_files: List[str]) -> Dict[str, List[str]]:
        existing: Dict[str, List[str]] = {}
        test_dirs = self._find_test_directories()

        for target in target_files:
            file_name = os.path.basename(target)
            name_no_ext = os.path.splitext(file_name)[0]
            possible_test_names = [f"test_{file_name}", f"{name_no_ext}_test.py"]
            found = []
            for test_dir in test_dirs:
                for test_name in possible_test_names:
                    candidate = os.path.join(self.repo_path, test_dir, test_name)
                    if os.path.exists(candidate):
                        found.append(os.path.join(test_dir, test_name))
            target_dir = os.path.dirname(target)
            for test_name in possible_test_names:
                candidate = os.path.join(self.repo_path, target_dir, test_name)
                if os.path.exists(candidate):
                    found.append(os.path.join(target_dir, test_name))
            existing[target] = found

        return existing

    def _find_test_directories(self) -> List[str]:
        candidates = ['tests', 'test', 'testing', '__tests__', 'spec']
        existing = []
        for cand in candidates:
            cand_path = os.path.join(self.repo_path, cand)
            if os.path.isdir(cand_path):
                existing.append(cand)
        return existing

    def generate_test_stubs(
        self, code_map: Dict[str, str], architecture_contract: str = ""
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for file_path, code in code_map.items():
            test_code = self._generate_test_file(file_path, code)
            if test_code:
                test_file = self._derive_test_file_path(file_path)
                result[test_file] = test_code
        return result

    def _derive_test_file_path(self, source_file: str) -> str:
        directory = os.path.dirname(source_file)
        file_name = os.path.basename(source_file)
        name_no_ext = os.path.splitext(file_name)[0]
        return os.path.join("tests", directory, f"test_{name_no_ext}.py")

    def _generate_test_file(self, file_path: str, code: str) -> Optional[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None

        module_name = os.path.splitext(os.path.basename(file_path))[0]
        import_path = self._file_to_import(file_path)

        functions: List[Tuple[str, List[str], bool]] = []
        classes: List[Tuple[str, List[Tuple[str, List[str], bool]]]] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                args = [a.arg for a in node.args.args if a.arg != 'self']
                functions.append((node.name, args, False))
            elif isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith('_'):
                args = [a.arg for a in node.args.args if a.arg != 'self']
                functions.append((node.name, args, True))
            elif isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
                methods = []
                for item in ast.iter_child_nodes(node):
                    if isinstance(item, ast.FunctionDef) and not item.name.startswith('_'):
                        m_args = [a.arg for a in item.args.args if a.arg not in ('self', 'cls')]
                        methods.append((item.name, m_args, False))
                    elif isinstance(item, ast.AsyncFunctionDef) and not item.name.startswith('_'):
                        m_args = [a.arg for a in item.args.args if a.arg not in ('self', 'cls')]
                        methods.append((item.name, m_args, True))
                if methods:
                    classes.append((node.name, methods))

        if not functions and not classes:
            return None

        func_names = [f[0] for f in functions]
        lines = [
            f'"""',
            f'Auto-generated baseline tests for {module_name}.',
            f'',
            f'WARNING: Tests cover happy path only.',
            f'         Edge cases, error paths, and mocks MUST be added manually.',
            f'"""',
            f'import pytest',
        ]
        if func_names:
            lines.append(f'from {import_path} import {", ".join(func_names)}')
        if classes:
            cls_names = [c[0] for c in classes]
            lines.append(f'from {import_path} import {", ".join(cls_names)}')
        lines.append('')
        lines.append('')

        for func_name, args, is_async in functions:
            lines.extend(self._generate_func_test(func_name, args, is_async))

        for cls_name, methods in classes:
            for method_name, args, is_async in methods:
                lines.extend(
                    self._generate_method_test(cls_name, method_name, args, is_async)
                )

        return '\n'.join(lines)

    def _generate_func_test(
        self, func_name: str, args: List[str], is_async: bool
    ) -> List[str]:
        arg_examples = self._generate_arg_examples(args)
        arg_string = ', '.join(str(a) for a in arg_examples)

        if is_async:
            return [
                '',
                '@pytest.mark.asyncio',
                f'async def test_{func_name}_happy_path():',
                f'    """Happy path test for {func_name}."""',
                f'    result = await {func_name}({arg_string})',
                f'    # TODO: Add meaningful assertions based on expected behavior',
                f'    assert result is not None  # Minimum sanity check',
                '',
            ]
        else:
            return [
                '',
                f'def test_{func_name}_happy_path():',
                f'    """Happy path test for {func_name}."""',
                f'    result = {func_name}({arg_string})',
                f'    # TODO: Add meaningful assertions based on expected behavior',
                f'    assert result is not None  # Minimum sanity check',
                '',
            ]

    def _generate_method_test(
        self, cls_name: str, method_name: str, args: List[str], is_async: bool
    ) -> List[str]:
        arg_examples = self._generate_arg_examples(args)
        arg_string = ', '.join(str(a) for a in arg_examples)

        if is_async:
            return [
                '',
                '@pytest.mark.asyncio',
                f'async def test_{cls_name}_{method_name}_happy_path():',
                f'    """Happy path test for {cls_name}.{method_name}."""',
                f'    instance = {cls_name}()  # TODO: Provide constructor args if needed',
                f'    result = await instance.{method_name}({arg_string})',
                f'    assert result is not None  # Minimum sanity check',
                '',
            ]
        else:
            return [
                '',
                f'def test_{cls_name}_{method_name}_happy_path():',
                f'    """Happy path test for {cls_name}.{method_name}."""',
                f'    instance = {cls_name}()  # TODO: Provide constructor args if needed',
                f'    result = instance.{method_name}({arg_string})',
                f'    assert result is not None  # Minimum sanity check',
                '',
            ]

    def _generate_arg_examples(self, args: List[str]) -> List[str]:
        value_map = {
            'path': '"test_path"', 'file': '"test_file.txt"',
            'name': '"test_name"', 'url': '"https://example.com"',
            'key': '"test_key"', 'id': '1', 'index': '0',
            'count': '10', 'limit': '100', 'size': '1024',
            'data': 'bytes([1, 2, 3])', 'text': '"hello world"',
            'config': '{}', 'options': '{}', 'kwargs': '{}',
            'args': '[]', 'items': '[]', 'value': '42',
            'flag': 'True', 'enabled': 'True', 'timeout': '30',
        }
        result = []
        for arg in args:
            if arg in value_map:
                result.append(value_map[arg])
            else:
                result.append(f'"mock_{arg}"')
        return result

    def _file_to_import(self, file_path: str) -> str:
        rel = file_path.replace('.py', '').replace('/', '.').replace('\\', '.')
        rel = re.sub(r'\.?__init__$', '', rel)
        return rel
