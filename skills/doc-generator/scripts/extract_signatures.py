#!/usr/bin/env python3
"""extract_signatures.py — Extract class, method, and function signatures from source code.

This script is part of the doc-generator skill. It parses source files to
extract structural information (classes, methods, functions, parameters,
return types, existing docstrings) into a JSON format that the agent can
use to generate documentation.

Supported languages:
    - Python (.py)     — uses the `ast` module for reliable parsing
    - C# (.cs)         — uses regex-based extraction (no external dependencies)
    - TypeScript (.ts)  — uses regex-based extraction (no external dependencies)

Usage:
    python extract_signatures.py [OPTIONS] <file_or_directory>

Arguments:
    file_or_directory       A single source file or a directory to scan recursively

Options:
    --language LANG         Force language detection (python, csharp, typescript).
                            If omitted, detected from file extension.
    --exclude PATTERN       Glob pattern(s) to exclude (e.g., "**/test_*", "**/node_modules/**").
                            Can be specified multiple times.
    --output PATH           Write JSON to this file (default: stdout)
    --include-private       Include private/internal members (prefixed with _ or private keyword)

Output format:
    {
        "source": "path/to/file_or_dir",
        "language": "python",
        "extracted_at": "2026-04-13T12:00:00Z",
        "files": [
            {
                "path": "src/auth.py",
                "classes": [
                    {
                        "name": "AuthManager",
                        "docstring": "Manages user authentication.",
                        "bases": ["BaseManager"],
                        "methods": [
                            {
                                "name": "validate_token",
                                "docstring": "Check if a JWT token is valid.",
                                "parameters": [
                                    { "name": "token", "type": "str", "default": null },
                                    { "name": "strict", "type": "bool", "default": "True" }
                                ],
                                "return_type": "bool",
                                "is_async": false,
                                "is_static": false,
                                "is_property": false,
                                "decorators": []
                            }
                        ]
                    }
                ],
                "functions": [
                    {
                        "name": "create_token",
                        "docstring": "Generate a new JWT token.",
                        "parameters": [...],
                        "return_type": "str",
                        "is_async": true,
                        "decorators": []
                    }
                ],
                "constants": [
                    { "name": "DEFAULT_TIMEOUT", "type": "int", "value": "30" }
                ]
            }
        ],
        "summary": {
            "total_files": 3,
            "total_classes": 5,
            "total_functions": 12,
            "total_methods": 28
        }
    }
"""

import ast
import json
import re
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

EXTENSION_MAP = {
    ".py": "python",
    ".cs": "csharp",
    ".ts": "typescript",
    ".tsx": "typescript",
}


def detect_language(file_path: str) -> str | None:
    """Detect programming language from file extension.

    Args:
        file_path: Path to the source file.

    Returns:
        Language identifier string, or None if unrecognized.
    """
    ext = Path(file_path).suffix.lower()
    return EXTENSION_MAP.get(ext)


# ---------------------------------------------------------------------------
# Python extractor (AST-based — most reliable)
# ---------------------------------------------------------------------------

def _get_docstring(node: ast.AST) -> str | None:
    """Extract docstring from an AST node if present."""
    return ast.get_docstring(node)


def _get_type_annotation(node: ast.AST | None) -> str | None:
    """Convert a type annotation AST node to a string representation.

    Args:
        node: An AST node representing a type annotation (or None).

    Returns:
        String representation of the type, or None if no annotation.
    """
    if node is None:
        return None
    return ast.unparse(node)


def _extract_python_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    """Extract function/method signature from a Python AST node.

    Args:
        node: A FunctionDef or AsyncFunctionDef AST node.

    Returns:
        Dict with name, docstring, parameters, return_type, decorators, etc.
    """
    params = []
    args = node.args

    # Positional args (including self/cls which we'll keep for transparency)
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        default_idx = i - defaults_offset
        default = ast.unparse(args.defaults[default_idx]) if default_idx >= 0 else None
        params.append({
            "name": arg.arg,
            "type": _get_type_annotation(arg.annotation),
            "default": default,
        })

    # *args
    if args.vararg:
        params.append({
            "name": f"*{args.vararg.arg}",
            "type": _get_type_annotation(args.vararg.annotation),
            "default": None,
        })

    # Keyword-only args
    kw_defaults = args.kw_defaults
    for i, arg in enumerate(args.kwonlyargs):
        default = ast.unparse(kw_defaults[i]) if kw_defaults[i] is not None else None
        params.append({
            "name": arg.arg,
            "type": _get_type_annotation(arg.annotation),
            "default": default,
        })

    # **kwargs
    if args.kwarg:
        params.append({
            "name": f"**{args.kwarg.arg}",
            "type": _get_type_annotation(args.kwarg.annotation),
            "default": None,
        })

    decorators = [ast.unparse(d) for d in node.decorator_list]

    return {
        "name": node.name,
        "docstring": _get_docstring(node),
        "parameters": params,
        "return_type": _get_type_annotation(node.returns),
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "is_static": any(d in ("staticmethod",) for d in decorators),
        "is_property": any(d in ("property",) for d in decorators),
        "decorators": decorators,
    }


def _extract_python_class(node: ast.ClassDef) -> dict:
    """Extract class signature and its methods from a Python AST node.

    Args:
        node: A ClassDef AST node.

    Returns:
        Dict with name, docstring, bases, and methods list.
    """
    bases = [ast.unparse(b) for b in node.bases]
    methods = []

    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_extract_python_function(item))

    return {
        "name": node.name,
        "docstring": _get_docstring(node),
        "bases": bases,
        "methods": methods,
    }


def extract_python(source: str, file_path: str, include_private: bool = False) -> dict:
    """Extract all signatures from a Python source file.

    Args:
        source: The Python source code as a string.
        file_path: Path to the file (for reporting).
        include_private: If False, skip names starting with underscore
                        (except __init__ and __new__).

    Returns:
        Dict with path, classes, functions, and constants.
    """
    tree = ast.parse(source, filename=file_path)

    classes = []
    functions = []
    constants = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            if not include_private and node.name.startswith("_"):
                continue
            cls = _extract_python_class(node)
            # Filter private methods unless requested
            if not include_private:
                cls["methods"] = [
                    m for m in cls["methods"]
                    if not m["name"].startswith("_") or m["name"] in ("__init__", "__new__")
                ]
            classes.append(cls)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not include_private and node.name.startswith("_"):
                continue
            functions.append(_extract_python_function(node))

        # Module-level assignments that look like constants (UPPER_CASE)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants.append({
                        "name": target.id,
                        "type": _get_type_annotation(getattr(node, "type_comment", None)),
                        "value": ast.unparse(node.value)[:200],  # Truncate long values
                    })
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name.isupper():
                constants.append({
                    "name": name,
                    "type": _get_type_annotation(node.annotation),
                    "value": ast.unparse(node.value)[:200] if node.value else None,
                })

    return {
        "path": file_path,
        "classes": classes,
        "functions": functions,
        "constants": constants,
    }


# ---------------------------------------------------------------------------
# C# extractor (regex-based)
# ---------------------------------------------------------------------------

# Matches: public class Foo : Bar, IBaz
CS_CLASS_RE = re.compile(
    r"(?:(?P<access>public|internal|private|protected)\s+)?"
    r"(?:(?:static|abstract|sealed|partial)\s+)*"
    r"class\s+(?P<name>\w+)"
    r"(?:\s*:\s*(?P<bases>[^{]+))?"
    r"\s*\{",
    re.MULTILINE,
)

# Matches: public async Task<string> DoThing(int x, string y = "default")
CS_METHOD_RE = re.compile(
    r"(?:(?P<access>public|internal|private|protected)\s+)?"
    r"(?:(?:static|virtual|override|abstract|async)\s+)*"
    r"(?P<return_type>[\w<>\[\],\s?]+?)\s+"
    r"(?P<name>\w+)\s*"
    r"\((?P<params>[^)]*)\)",
    re.MULTILINE,
)

# Matches: /// <summary>...</summary>
CS_DOC_RE = re.compile(r"///\s*<summary>\s*(.*?)\s*</summary>", re.DOTALL)


def extract_csharp(source: str, file_path: str, include_private: bool = False) -> dict:
    """Extract signatures from a C# source file using regex.

    This is a best-effort extraction. Complex generics, nested classes, and
    some edge cases may not parse perfectly. The output is intended as a
    starting point for documentation, not a compiler-grade AST.

    Args:
        source: C# source code as a string.
        file_path: Path to the file.
        include_private: Include private members.

    Returns:
        Dict with path, classes, functions (top-level), and constants.
    """
    classes = []
    functions = []

    for match in CS_CLASS_RE.finditer(source):
        access = match.group("access") or "internal"
        if not include_private and access == "private":
            continue

        name = match.group("name")
        bases_raw = match.group("bases")
        bases = [b.strip() for b in bases_raw.split(",")] if bases_raw else []

        # Look for XML doc comment above the class
        pre_text = source[:match.start()]
        doc_match = list(CS_DOC_RE.finditer(pre_text))
        docstring = doc_match[-1].group(1).strip() if doc_match else None

        # Find methods within the class body (rough: next N chars)
        class_start = match.end()
        # Find matching closing brace (simplified — doesn't handle nested braces perfectly)
        brace_depth = 1
        pos = class_start
        while pos < len(source) and brace_depth > 0:
            if source[pos] == "{":
                brace_depth += 1
            elif source[pos] == "}":
                brace_depth -= 1
            pos += 1
        class_body = source[class_start:pos]

        methods = []
        for m_match in CS_METHOD_RE.finditer(class_body):
            m_access = m_match.group("access") or "private"
            if not include_private and m_access == "private":
                continue
            m_name = m_match.group("name")
            if m_name in (name,):  # Skip constructor (same name as class)
                continue

            # Parse parameters
            params_raw = m_match.group("params").strip()
            params = []
            if params_raw:
                for p in params_raw.split(","):
                    p = p.strip()
                    parts = p.rsplit(" ", 1)
                    if len(parts) == 2:
                        p_type, p_name = parts
                        default = None
                        if "=" in p_name:
                            p_name, default = p_name.split("=", 1)
                            default = default.strip()
                        params.append({
                            "name": p_name.strip(),
                            "type": p_type.strip(),
                            "default": default,
                        })

            methods.append({
                "name": m_name,
                "docstring": None,  # Would need per-method doc parsing
                "parameters": params,
                "return_type": m_match.group("return_type").strip(),
                "is_async": "async" in (source[m_match.start():m_match.start()+50] or ""),
                "is_static": "static" in (source[m_match.start():m_match.start()+50] or ""),
                "is_property": False,
                "decorators": [],
            })

        classes.append({
            "name": name,
            "docstring": docstring,
            "bases": bases,
            "methods": methods,
        })

    return {
        "path": file_path,
        "classes": classes,
        "functions": functions,
        "constants": [],
    }


# ---------------------------------------------------------------------------
# TypeScript extractor (regex-based)
# ---------------------------------------------------------------------------

# Matches: export class Foo extends Bar implements IBaz {
TS_CLASS_RE = re.compile(
    r"(?:export\s+)?class\s+(?P<name>\w+)"
    r"(?:\s+extends\s+(?P<extends>\w+))?"
    r"(?:\s+implements\s+(?P<implements>[^{]+))?"
    r"\s*\{",
    re.MULTILINE,
)

# Matches: async functionName(param: type, param2?: type): ReturnType
TS_FUNC_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*"
    r"\((?P<params>[^)]*)\)"
    r"(?:\s*:\s*(?P<return_type>[^{;]+))?"
    r"\s*[{;]",
    re.MULTILINE,
)

# Matches: /** ... */
TS_DOC_RE = re.compile(r"/\*\*\s*(.*?)\s*\*/", re.DOTALL)


def extract_typescript(source: str, file_path: str, include_private: bool = False) -> dict:
    """Extract signatures from a TypeScript source file using regex.

    Args:
        source: TypeScript source code.
        file_path: Path to the file.
        include_private: Include private members.

    Returns:
        Dict with path, classes, functions, and constants.
    """
    classes = []
    functions = []

    for match in TS_CLASS_RE.finditer(source):
        name = match.group("name")
        bases = []
        if match.group("extends"):
            bases.append(match.group("extends"))
        if match.group("implements"):
            bases.extend(i.strip() for i in match.group("implements").split(","))

        # Look for JSDoc above
        pre_text = source[:match.start()]
        doc_matches = list(TS_DOC_RE.finditer(pre_text))
        docstring = doc_matches[-1].group(1).strip() if doc_matches else None

        classes.append({
            "name": name,
            "docstring": docstring,
            "bases": bases,
            "methods": [],  # Would need deeper parsing for class body methods
        })

    for match in TS_FUNC_RE.finditer(source):
        name = match.group("name")
        if not include_private and name.startswith("_"):
            continue

        params_raw = match.group("params").strip()
        params = []
        if params_raw:
            for p in params_raw.split(","):
                p = p.strip()
                optional = "?" in p
                p = p.replace("?", "")
                if ":" in p:
                    p_name, p_type = p.split(":", 1)
                    default = None
                    if "=" in p_type:
                        p_type, default = p_type.split("=", 1)
                        default = default.strip()
                    params.append({
                        "name": p_name.strip(),
                        "type": p_type.strip() + (" (optional)" if optional else ""),
                        "default": default,
                    })
                else:
                    params.append({"name": p.strip(), "type": None, "default": None})

        # Look for JSDoc above
        pre_text = source[:match.start()]
        doc_matches = list(TS_DOC_RE.finditer(pre_text))
        docstring = doc_matches[-1].group(1).strip() if doc_matches else None

        functions.append({
            "name": name,
            "docstring": docstring,
            "parameters": params,
            "return_type": match.group("return_type").strip() if match.group("return_type") else None,
            "is_async": "async" in source[max(0, match.start()-10):match.start()],
            "decorators": [],
        })

    return {
        "path": file_path,
        "classes": classes,
        "functions": functions,
        "constants": [],
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

EXTRACTORS = {
    "python": extract_python,
    "csharp": extract_csharp,
    "typescript": extract_typescript,
}


def extract_file(
    file_path: str,
    language: str | None = None,
    include_private: bool = False,
) -> dict | None:
    """Extract signatures from a single source file.

    Args:
        file_path: Path to the source file.
        language: Force language (or auto-detect from extension).
        include_private: Include private members.

    Returns:
        Extraction dict, or None if the file can't be parsed.
    """
    lang = language or detect_language(file_path)
    if not lang or lang not in EXTRACTORS:
        return None

    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
    try:
        return EXTRACTORS[lang](source, file_path, include_private)
    except SyntaxError as e:
        print(f"WARNING: Syntax error in {file_path}: {e}", file=sys.stderr)
        return None


def extract_directory(
    dir_path: str,
    language: str | None = None,
    exclude_patterns: list[str] | None = None,
    include_private: bool = False,
) -> list[dict]:
    """Recursively extract signatures from all supported files in a directory.

    Args:
        dir_path: Path to the directory to scan.
        language: Force language for all files (or auto-detect).
        exclude_patterns: Glob patterns to skip (matched against relative paths).
        include_private: Include private members.

    Returns:
        List of extraction dicts, one per file.
    """
    exclude = exclude_patterns or []
    results = []
    root = Path(dir_path)

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        rel = str(file_path.relative_to(root))

        # Check exclusions
        if any(fnmatch(rel, pat) for pat in exclude):
            continue

        result = extract_file(str(file_path), language, include_private)
        if result:
            result["path"] = rel  # Use relative path in output
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Parse command-line arguments and run the signature extractor."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract class, method, and function signatures from source code."
    )
    parser.add_argument(
        "source",
        help="A single source file or directory to scan recursively",
    )
    parser.add_argument(
        "--language",
        choices=["python", "csharp", "typescript"],
        help="Force language detection (default: auto-detect from extension)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern to exclude (can specify multiple times)",
    )
    parser.add_argument(
        "--output",
        help="Write JSON to file (default: stdout)",
    )
    parser.add_argument(
        "--include-private",
        action="store_true",
        help="Include private/internal members",
    )

    args = parser.parse_args()
    source_path = Path(args.source)

    if not source_path.exists():
        print(f"ERROR: {args.source} does not exist", file=sys.stderr)
        sys.exit(1)

    if source_path.is_file():
        files = [extract_file(str(source_path), args.language, args.include_private)]
        files = [f for f in files if f is not None]
    else:
        files = extract_directory(
            str(source_path), args.language, args.exclude, args.include_private
        )

    # Count totals
    total_classes = sum(len(f["classes"]) for f in files)
    total_functions = sum(len(f["functions"]) for f in files)
    total_methods = sum(
        sum(len(c["methods"]) for c in f["classes"])
        for f in files
    )

    result = {
        "source": str(args.source),
        "language": args.language or "auto-detected",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "summary": {
            "total_files": len(files),
            "total_classes": total_classes,
            "total_functions": total_functions,
            "total_methods": total_methods,
        },
    }

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
