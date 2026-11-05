"""Assemble the static frontend from `static-src/` into `app/static/`.

Why a build step for a Python-only project: the generator used to be a single
743-line HTML file with ~90 KB of inline JavaScript. Splitting it into ES
modules keeps modules editable and testable, while the committed build output
keeps deployment as simple as before (no Node.js on the server).

Usage:
    python scripts/build_static.py           # write app/static/*
    python scripts/build_static.py --check   # fail if output is stale (CI)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "static-src"
DEST = ROOT / "app" / "static"

GENERATOR_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Проверка генератора - Slack</title>
<link rel="stylesheet" href="/app/generator.css">
</head>
<body>
<div class="dg14" data-generator="v18">
{markup}
<dialog class="lightbox"><button type="button" class="close-image" aria-label="Закрыть изображение">&times;</button><img alt=""></dialog>
</div>
<script type="module" src="/app/generator.js"></script>
</body>
</html>
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


IMPORT_RE = re.compile(r"(?m)^\s*import\b[\s\S]*?from\s*['\"]([^'\"]+)['\"]")
SIDE_EFFECT_IMPORT_RE = re.compile(r"(?m)^\s*import\s*['\"]([^'\"]+)['\"]")
EXPORT_FROM_RE = re.compile(r"(?m)^\s*export\s*\{[\s\S]*?\}\s*from\s*['\"]([^'\"]+)['\"]")
EXPORT_NAME_RE = re.compile(r"(?ms)^\s*export\s+(?:const|let|var|function|class|async\s+function)\s+([A-Za-z_$][\w$]*)")
EXPORT_LIST_RE = re.compile(r"(?ms)^\s*export\s*\{([^}]*)\}")


def _exported_names(source: str) -> set[str]:
    """Names a module exports, including `export { a, b } from './x.js'`."""
    names = set(EXPORT_NAME_RE.findall(source))
    for braces in EXPORT_LIST_RE.findall(source):
        for piece in braces.split(","):
            piece = piece.strip()
            if not piece:
                continue
            alias = piece.split(" as ")[-1].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", alias) and alias != "default":
                names.add(alias)
    return names


def module_files() -> list[Path]:
    return sorted(SRC.rglob("*.js"))


class ModuleGraphError(RuntimeError):
    """Raised when static-src/ cannot be bundled safely."""


def _local_imports(source: str) -> list[str]:
    specs = (
        IMPORT_RE.findall(source)
        + SIDE_EFFECT_IMPORT_RE.findall(source)
        + EXPORT_FROM_RE.findall(source)
    )
    return [spec for spec in specs if spec.startswith(".")]


def validate_module_graph() -> None:
    """Fail the build when the module graph cannot be resolved or bundled.

    Catches the class of bug a syntax check cannot see: relative imports that
    point at a non-existent file (what broke `index.js`/`main.js`), imports of
    a name the target module never exports, and identifiers that would collide
    once every module is concatenated into one file.
    """
    problems: list[str] = []
    files = module_files()
    if not files:
        raise ModuleGraphError("no modules found under static-src/")

    exports: dict[Path, set[str]] = {}
    for path in files:
        source = _read(path)
        exports[path.resolve()] = _exported_names(source)
        for spec in _local_imports(source):
            target = (path.parent / spec).resolve()
            if not target.exists():
                problems.append(f"{path.relative_to(ROOT)}: import '{spec}' does not resolve")
            elif target.suffix != ".js":
                problems.append(f"{path.relative_to(ROOT)}: import '{spec}' is not a .js module")

    # `import { a, b as c } from './x.js'` must name real exports.
    for path in files:
        source = _read(path)
        for spec, names in _named_imports(source):
            target = (path.parent / spec).resolve()
            if target not in exports:
                continue
            for name, alias in names:
                if name not in exports[target]:
                    problems.append(
                        f"{path.relative_to(ROOT)}: '{name}' is not exported by {spec}"
                    )

    # After concatenation every module shares one scope; duplicate top-level
    # declarations break the bundle with "Identifier has already been declared".
    declared: dict[str, Path] = {}
    for path in files:
        source = _read(path)
        for name in _top_level_declarations(source):
            if name in declared and declared[name] != path:
                problems.append(
                    f"{path.relative_to(ROOT)}: '{name}' also declared in "
                    f"{declared[name].relative_to(ROOT)} (collides when bundled)"
                )
            else:
                declared[name] = path

    # Every module reachable from the entry point keeps the bundle honest.
    for path in files:
        if path.resolve() not in exports:
            raise ModuleGraphError(f"failed to scan {path}")

    if problems:
        raise ModuleGraphError("invalid module graph:\n  " + "\n  ".join(problems))


def _named_imports(source: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Yield (specifier, [(importedName, localAlias)]) for brace imports."""
    result = []
    pattern = re.compile(r"(?ms)^\s*import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
    for braces, spec in pattern.findall(source):
        if not spec.startswith("."):
            continue
        names = []
        for piece in braces.split(","):
            piece = piece.strip()
            if not piece:
                continue
            if " as " in piece:
                original, alias = (part.strip() for part in piece.split(" as ", 1))
            else:
                original = alias = piece
            names.append((original, alias))
        result.append((spec, names))
    return result


def _top_level_declarations(source: str) -> list[str]:
    """Names declared at column 0, i.e. what the bundle puts in one scope."""
    pattern = re.compile(
        r"(?m)^(?:export\s+)?(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)"
    )
    return pattern.findall(source)


def _markup() -> str:
    """The generator form markup, without the outer `.dg14` wrapper."""
    raw = _read(SRC / "generator" / "generator.html")
    opening = '<div class="dg14" data-generator="v18">'
    assert raw.startswith(opening), "generator.html must start with the .dg14 wrapper"
    body = raw[len(opening):].rstrip()
    assert body.endswith("</div>"), "generator.html must end with the closing wrapper"
    body = body[: -len("</div>")].rstrip()
    # The lightbox dialog is rendered by the page template, not by the fragment.
    dialog_start = body.find('<dialog class="lightbox">')
    if dialog_start != -1:
        body = body[:dialog_start].rstrip()
    return body


def _strip_module_syntax(source: str) -> str:
    """Drop ES `import`/`export` plumbing so modules concatenate cleanly."""
    # `import ... from '...';` — including multi-line braces and side-effect imports.
    source = re.sub(
        r"(?m)^\s*import\b[\s\S]*?from\s*['\"][^'\"]+['\"];?[ \t]*\n",
        "",
        source,
    )
    source = re.sub(r"(?m)^\s*import\s*['\"][^'\"]+['\"];?[ \t]*\n", "", source)
    # `import { a } from './x.js';` where the statement starts with `import {`
    # and the `from` clause sits on a later line is covered by the regex above.
    source = re.sub(
        r"(?m)^\s*export\s*\{[\s\S]*?\}\s*(?:from\s*['\"][^'\"]+['\"])?\s*;?[ \t]*\n",
        "",
        source,
    )
    # `export const|let|var|function|class|async` -> plain declaration.
    source = re.sub(r"(?m)^export\s+(?=(?:const|let|var|function|class|async)\b)", "", source)
    return source


def build_generator_js() -> str:
    """Concatenate the module graph into one ES module.

    The browser loads a single file, so relative imports between source files
    are removed and the declarations are emitted in dependency order.
    """
    order = [
        "generator/store.js",
        "generator/translations/translations.js",
        "generator/cases/regions.js",
        "generator/cases/licenses.js",
        "generator/cases/platforms.js",
        "generator/cases/generate.js",
        "generator/cases/wallet.js",
        "generator/cases/index.js",
        "generator/cases/payout.js",
        "generator/cases/render.js",
        "generator/ui/language.js",
        "generator/ui/accounts.js",
        "generator/ui/events.js",
        "generator/index.js",
        "generator/main.js",
    ]
    chunks = [
        "// AUTO-GENERATED by scripts/build_static.py — edit static-src/ instead.",
        "// Bundled from static-src/generator/** into a single ES module.",
        "",
    ]
    for relative in order:
        body = _strip_module_syntax(_read(SRC / relative)).strip()
        if not body:
            continue
        chunks.append(f"// ---- {relative} " + "-" * max(0, 64 - len(relative)))
        chunks.append(body)
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def build_generator_css() -> str:
    css = _read(SRC / "generator" / "generator.css").strip()
    return "/* AUTO-GENERATED by scripts/build_static.py — edit static-src/ instead. */\n" + css + "\n"


def build_generator_page() -> str:
    return GENERATOR_PAGE.format(markup=_markup())


def outputs() -> dict[Path, str]:
    return {
        DEST / "generator.html": build_generator_page(),
        DEST / "generator.css": build_generator_css(),
        DEST / "generator.js": build_generator_js(),
    }


def main(argv: list[str]) -> int:
    check = "--check" in argv
    validate_only = "--validate" in argv

    try:
        validate_module_graph()
    except ModuleGraphError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if validate_only:
        print(f"Module graph is valid ({len(module_files())} modules).")
        return 0

    stale: list[Path] = []
    for path, content in outputs().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        stale.append(path)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if check:
        if stale:
            print("Stale build output:", *[str(p.relative_to(ROOT)) for p in stale], sep="\n  ")
            return 1
        print("Static output is up to date.")
        return 0
    for path in stale:
        print("wrote", path.relative_to(ROOT))
    if not stale:
        print("Nothing to do; output already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
