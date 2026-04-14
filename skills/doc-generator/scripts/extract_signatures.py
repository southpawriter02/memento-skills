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
import unicodedata
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path


# ---------------------------------------------------------------------------
# Docstring language classification (MS-DES-0003)
# ---------------------------------------------------------------------------
#
# The classifier lets the doc-generator skill detect docstrings written in a
# language other than the target language (English by default) so the agent
# can translate them before they land in reference-doc prose. It operates on
# pure character-script counting via `unicodedata` — no third-party deps, no
# network, deterministic across runs. See `docs/design/doc-generator-
# translation-pass.md` for the full rationale and acceptance criteria.

# Unicode `unicodedata.name()` prefixes we map to short script labels. Keys
# are matched against the first whitespace-separated word of a character's
# Unicode name (uppercased). The list is not exhaustive — scripts we do not
# map fall through to "other" and still participate in the non-target tally,
# so the classifier stays conservative without special-casing every script.
SCRIPT_NAME_PREFIXES: dict[str, str] = {
    "LATIN": "latin",
    "CYRILLIC": "cyrillic",
    "GREEK": "greek",
    "ARABIC": "arabic",
    "HEBREW": "hebrew",
    "DEVANAGARI": "devanagari",
    "BENGALI": "bengali",
    "TAMIL": "tamil",
    "THAI": "thai",
    "LAO": "lao",
    "TIBETAN": "tibetan",
    "MYANMAR": "myanmar",
    "GEORGIAN": "georgian",
    "ARMENIAN": "armenian",
    "ETHIOPIC": "ethiopic",
    "HIRAGANA": "hiragana",
    "KATAKANA": "katakana",
    "HANGUL": "hangul",
    # CJK unified ideographs (and their extensions / compatibility blocks)
    # all begin with "CJK" in their Unicode name. We collapse them under
    # "han" because Japanese Kanji, Chinese Hanzi, and Korean Hanja share
    # the same codepoints and cannot be disambiguated without context.
    "CJK": "han",
}

# The set of script labels the `--target-script` flag accepts. Built from the
# values above so the flag validation stays in sync with the mapping.
SUPPORTED_TARGET_SCRIPTS: frozenset[str] = frozenset(SCRIPT_NAME_PREFIXES.values())

# Classification thresholds. Tuned conservatively: a docstring that is 95%+
# target-script letters is `target`; 20% or less is `non_target`; everything
# between is `mixed`. These stay code constants (not CLI flags) so changes
# live in git history rather than in per-run invocations.
TARGET_RATIO_MIN = 0.95
NON_TARGET_RATIO_MAX = 0.20


def _script_for_char(char: str) -> str:
    """Return a short script label for a single character.

    Uses `unicodedata.name()` and maps the leading word to one of the
    script labels in `SCRIPT_NAME_PREFIXES`. Unknown / unnamed codepoints
    return "other" rather than raising, so a stray private-use character
    does not abort the whole classification pass.

    Args:
        char: A single-character string. Behavior is undefined for longer
              inputs; the function is always called with one char at a time.

    Returns:
        One of the values in `SCRIPT_NAME_PREFIXES`, or "other".
    """
    name = unicodedata.name(char, "")
    if not name:
        return "other"
    first_word = name.split(" ", 1)[0]
    return SCRIPT_NAME_PREFIXES.get(first_word, "other")


def classify_docstring_language(
    docstring: str | None,
    *,
    target_script: str = "latin",
    target_threshold: float = TARGET_RATIO_MIN,
    non_target_threshold: float = NON_TARGET_RATIO_MAX,
) -> tuple[str, list[str]]:
    """Classify a docstring as target / non_target / mixed / empty / unknown.

    The classifier counts letters (Unicode category starts with "L") by
    script, computes the fraction of letters in the target script, and
    assigns a label per the thresholds.

    Args:
        docstring: Raw docstring text as captured by the extractor. May be
                   None or empty; both are treated as `empty`.
        target_script: Script label for the target language. "latin" for
                       English, "han" for Chinese/Japanese source repos, etc.
        target_threshold: Minimum target-script letter ratio to classify as
                          `target`. Defaults to `TARGET_RATIO_MIN` (0.95).
        non_target_threshold: Maximum target-script letter ratio to classify
                              as `non_target`. Defaults to
                              `NON_TARGET_RATIO_MAX` (0.20).

    Returns:
        A pair `(classification, scripts)`. `classification` is one of
        "target", "non_target", "mixed", "empty", "unknown". `scripts` is a
        sorted, deduplicated list of the script labels observed among the
        letter characters (empty if no letters were found).
    """
    # Empty / whitespace-only → "empty", no scripts to report.
    if not docstring or not docstring.strip():
        return "empty", []

    # Tally letter characters by script. `unicodedata.category(char)` returns
    # a two-letter code; all letters start with "L" (Lu, Ll, Lt, Lo, Lm).
    # Non-letters (digits, punctuation, symbols, whitespace) are skipped so
    # a docstring like "Returns True." isn't diluted by the punctuation.
    script_counts: dict[str, int] = {}
    total_letters = 0
    for char in docstring:
        if not unicodedata.category(char).startswith("L"):
            continue
        total_letters += 1
        script = _script_for_char(char)
        script_counts[script] = script_counts.get(script, 0) + 1

    # No letters at all (digits / punctuation / whitespace only) → "unknown".
    # This is rare but can happen for docstrings like "1.0" or "* * *".
    if total_letters == 0:
        return "unknown", []

    # Compute the target-script ratio and classify. We also guard against a
    # target-script label that the mapping doesn't know about; in that case
    # the ratio is zero and the docstring falls into `non_target` (which is
    # semantically correct: nothing in it matches the target).
    target_count = script_counts.get(target_script, 0)
    target_ratio = target_count / total_letters
    scripts = sorted(script_counts.keys())

    if target_ratio >= target_threshold:
        return "target", scripts
    if target_ratio <= non_target_threshold:
        return "non_target", scripts
    return "mixed", scripts


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
        # Module-level docstring. Included so the translation pass can flag
        # files whose module-level prose is in a non-target language (the
        # `gateway.py` case that motivated MS-DES-0003).
        "module_docstring": _get_docstring(tree),
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
        # C# has no single "module docstring" — file-level XML-doc comments
        # are uncommon. We emit the field for schema symmetry with Python.
        "module_docstring": None,
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
        # TypeScript: no canonical "module docstring" convention. Leading
        # JSDoc usually attaches to the first declaration. Emit None for
        # schema symmetry; see Python extractor for the motivating case.
        "module_docstring": None,
        "classes": classes,
        "functions": functions,
        "constants": [],
    }


# ---------------------------------------------------------------------------
# Docstring-language annotation walker (MS-DES-0003)
# ---------------------------------------------------------------------------

def _annotate_entity(
    entity: dict,
    target_script: str,
    target_threshold: float,
    non_target_threshold: float,
    counts: dict[str, int],
) -> None:
    """Attach `docstring_language` and `docstring_scripts` to an entity dict.

    Mutates `entity` in place and increments the aggregate `counts` map.
    Safe to call on entities that have no `docstring` key — the function
    skips them silently so it can be dispatched uniformly across class,
    method, and function dicts.

    Args:
        entity: A dict representing a class, method, function, etc. If it
                does not have a "docstring" key (present and non-null or
                null), no annotation is attached.
        target_script: Script label considered "target" (e.g. "latin").
        target_threshold: Target-ratio cutoff for "target" classification.
        non_target_threshold: Target-ratio cutoff for "non_target".
        counts: Running tally keyed by classification label.
    """
    if "docstring" not in entity:
        return
    classification, scripts = classify_docstring_language(
        entity["docstring"],
        target_script=target_script,
        target_threshold=target_threshold,
        non_target_threshold=non_target_threshold,
    )
    entity["docstring_language"] = classification
    entity["docstring_scripts"] = scripts
    counts[classification] = counts.get(classification, 0) + 1


def _annotate_module_docstring(
    file_dict: dict,
    target_script: str,
    target_threshold: float,
    non_target_threshold: float,
    counts: dict[str, int],
) -> None:
    """Classify and annotate the module-level docstring for a file entry.

    Produces siblings `module_docstring_language` and
    `module_docstring_scripts` that the agent can inspect when deciding
    whether the file's top-level prose needs translation.
    """
    if "module_docstring" not in file_dict:
        return
    classification, scripts = classify_docstring_language(
        file_dict["module_docstring"],
        target_script=target_script,
        target_threshold=target_threshold,
        non_target_threshold=non_target_threshold,
    )
    file_dict["module_docstring_language"] = classification
    file_dict["module_docstring_scripts"] = scripts
    counts[classification] = counts.get(classification, 0) + 1


def annotate_docstring_languages(
    file_dict: dict,
    *,
    target_script: str = "latin",
    target_threshold: float = TARGET_RATIO_MIN,
    non_target_threshold: float = NON_TARGET_RATIO_MAX,
) -> dict[str, int]:
    """Walk a file extraction dict and annotate every docstring with language info.

    Mutates `file_dict` in place: every class / method / function / module
    docstring gets paired `*_language` and `*_scripts` fields. Returns an
    aggregate count of classifications for this single file so the caller
    can roll them up across the whole run.

    Args:
        file_dict: Output of one of the per-language extractors.
        target_script: Script label for the target language.
        target_threshold: See `classify_docstring_language`.
        non_target_threshold: See `classify_docstring_language`.

    Returns:
        Dict keyed by classification label ("target", "non_target", "mixed",
        "empty", "unknown") with integer counts. Labels not seen in this
        file are omitted.
    """
    counts: dict[str, int] = {}

    # Module-level docstring first (one per file, may be None).
    _annotate_module_docstring(
        file_dict, target_script, target_threshold, non_target_threshold, counts
    )

    # Classes and their methods.
    for cls in file_dict.get("classes", []):
        _annotate_entity(
            cls, target_script, target_threshold, non_target_threshold, counts
        )
        for method in cls.get("methods", []):
            _annotate_entity(
                method, target_script, target_threshold, non_target_threshold, counts
            )

    # Top-level functions.
    for func in file_dict.get("functions", []):
        _annotate_entity(
            func, target_script, target_threshold, non_target_threshold, counts
        )

    return counts


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
    *,
    target_script: str = "latin",
) -> dict | None:
    """Extract signatures from a single source file.

    After extraction, every docstring-bearing entity (module, class, method,
    function) gets `docstring_language` and `docstring_scripts` sibling
    fields via `annotate_docstring_languages`. See MS-DES-0003.

    Args:
        file_path: Path to the source file.
        language: Force language (or auto-detect from extension).
        include_private: Include private members.
        target_script: Script label considered "target" for docstring
                       classification. Defaults to "latin" (English).

    Returns:
        Extraction dict, or None if the file can't be parsed.
    """
    lang = language or detect_language(file_path)
    if not lang or lang not in EXTRACTORS:
        return None

    source = Path(file_path).read_text(encoding="utf-8", errors="replace")
    try:
        result = EXTRACTORS[lang](source, file_path, include_private)
    except SyntaxError as e:
        print(f"WARNING: Syntax error in {file_path}: {e}", file=sys.stderr)
        return None

    # Annotate docstrings in-place. The per-file counts are aggregated by
    # the caller (`extract_directory` / `main`) into a global summary.
    file_counts = annotate_docstring_languages(result, target_script=target_script)
    # Stash the per-file counts on the dict so the caller can roll them up
    # without re-walking. Keep it under a clearly-namespaced key to avoid
    # confusion with other future per-file totals.
    result["_language_counts"] = file_counts
    return result


def extract_directory(
    dir_path: str,
    language: str | None = None,
    exclude_patterns: list[str] | None = None,
    include_private: bool = False,
    *,
    target_script: str = "latin",
) -> list[dict]:
    """Recursively extract signatures from all supported files in a directory.

    Args:
        dir_path: Path to the directory to scan.
        language: Force language for all files (or auto-detect).
        exclude_patterns: Glob patterns to skip (matched against relative paths).
        include_private: Include private members.
        target_script: Script label forwarded to `extract_file` for
                       docstring-language classification.

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

        result = extract_file(
            str(file_path), language, include_private, target_script=target_script
        )
        if result:
            result["path"] = rel  # Use relative path in output
            results.append(result)

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _aggregate_language_counts(files: list[dict]) -> dict[str, int]:
    """Sum the per-file `_language_counts` dicts into a single tally.

    The keys that can appear are fixed ("target", "non_target", "mixed",
    "empty", "unknown"). Keys missing from any file default to zero so the
    returned dict always has the full set — the agent reading the summary
    shouldn't have to defensive-check.
    """
    totals = {"target": 0, "non_target": 0, "mixed": 0, "empty": 0, "unknown": 0}
    for f in files:
        for key, value in f.get("_language_counts", {}).items():
            totals[key] = totals.get(key, 0) + value
    return totals


def _strip_internal_keys(files: list[dict]) -> None:
    """Remove helper-only keys (prefix `_`) before JSON serialization.

    Per-file `_language_counts` is an intermediate — the aggregate form in
    the top-level summary is what external consumers should read.
    """
    for f in files:
        for key in list(f.keys()):
            if key.startswith("_"):
                del f[key]


def _print_translation_summary(
    totals: dict[str, int], file_count: int, target_script: str
) -> None:
    """Print the human-readable translation summary used by --translation-summary-only."""
    non_target = totals.get("non_target", 0)
    mixed = totals.get("mixed", 0)
    translatable = non_target + mixed
    total_docstrings = sum(totals.values())

    if total_docstrings == 0:
        print("No docstrings found.")
        return

    print(f"Scanned {file_count} file(s); target script: {target_script}.")
    print(f"  {totals.get('target', 0):>4}  target  (no translation needed)")
    print(f"  {non_target:>4}  non_target  (translate)")
    print(f"  {mixed:>4}  mixed  (translate; contains non-target fragments)")
    print(f"  {totals.get('empty', 0):>4}  empty  (skip)")
    print(f"  {totals.get('unknown', 0):>4}  unknown  (inspect manually)")
    print()
    if translatable == 0:
        print("No translation pass needed — all docstrings are in the target script.")
    else:
        print(
            f"Translation pass recommended: {translatable} docstring(s) need review."
        )


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
    # MS-DES-0003: docstring-language classification flags.
    parser.add_argument(
        "--target-script",
        default="latin",
        help=(
            "Unicode script label considered 'target' for docstring classification "
            "(default: latin). Supported: "
            + ", ".join(sorted(SUPPORTED_TARGET_SCRIPTS))
        ),
    )
    parser.add_argument(
        "--translation-summary-only",
        action="store_true",
        help=(
            "Print a human-readable docstring-language summary and exit "
            "without emitting the full JSON. Useful for deciding whether a "
            "translation pass is needed before regenerating docs."
        ),
    )

    args = parser.parse_args()
    source_path = Path(args.source)

    # Validate target-script up front so bad flags fail with a clear error
    # before we do any file I/O.
    if args.target_script not in SUPPORTED_TARGET_SCRIPTS:
        print(
            f'ERROR: unrecognized Unicode script "{args.target_script}". '
            f"Supported: {', '.join(sorted(SUPPORTED_TARGET_SCRIPTS))}",
            file=sys.stderr,
        )
        sys.exit(2)

    if not source_path.exists():
        print(f"ERROR: {args.source} does not exist", file=sys.stderr)
        sys.exit(1)

    if source_path.is_file():
        files = [
            extract_file(
                str(source_path),
                args.language,
                args.include_private,
                target_script=args.target_script,
            )
        ]
        files = [f for f in files if f is not None]
    else:
        files = extract_directory(
            str(source_path),
            args.language,
            args.exclude,
            args.include_private,
            target_script=args.target_script,
        )

    # Aggregate docstring-language counts BEFORE stripping internal keys.
    language_counts = _aggregate_language_counts(files)

    # Summary-only fast path: print the tally, exit zero, skip the JSON.
    if args.translation_summary_only:
        _print_translation_summary(language_counts, len(files), args.target_script)
        sys.exit(0)

    # Count totals (existing behavior, unchanged).
    total_classes = sum(len(f["classes"]) for f in files)
    total_functions = sum(len(f["functions"]) for f in files)
    total_methods = sum(
        sum(len(c["methods"]) for c in f["classes"])
        for f in files
    )

    # Strip the per-file `_language_counts` helpers now that the aggregate
    # is computed. External consumers only need the summary-level view.
    _strip_internal_keys(files)

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
            # MS-DES-0003: aggregate docstring-language classifications.
            "docstring_language_counts": language_counts,
            "target_script": args.target_script,
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
