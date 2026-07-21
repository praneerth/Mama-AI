from __future__ import annotations

import ast
from collections import defaultdict, deque
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
REPORTS_DIR = BACKEND_DIR / "reports"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def path_to_module(path: Path) -> str:
    relative = path.relative_to(BACKEND_DIR).with_suffix("")
    parts = list(relative.parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def resolve_relative_import(
    current_module: str,
    current_path: Path,
    imported_module: str | None,
    level: int,
) -> str:
    if current_path.name == "__init__.py":
        package_parts = current_module.split(".")
    else:
        package_parts = current_module.split(".")[:-1]

    remove_count = max(level - 1, 0)

    if remove_count:
        package_parts = package_parts[:-remove_count]

    if imported_module:
        package_parts.extend(imported_module.split("."))

    return ".".join(package_parts)


python_files = sorted(
    path
    for path in APP_DIR.rglob("*.py")
    if "__pycache__" not in path.parts
)

for root_file in ("main.py", "run_gui.py", "voice_assistant.py"):
    candidate = BACKEND_DIR / root_file

    if candidate.exists():
        python_files.append(candidate)


module_paths = {
    path_to_module(path): path
    for path in python_files
}

known_modules = set(module_paths)

dependencies: dict[str, set[str]] = defaultdict(set)
syntax_errors: list[str] = []


for module_name, file_path in module_paths.items():
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except UnicodeDecodeError:
        source = file_path.read_text(encoding="utf-8", errors="replace")

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            syntax_errors.append(
                f"{file_path}:{exc.lineno}: {exc.msg}"
            )
            continue
    except SyntaxError as exc:
        syntax_errors.append(
            f"{file_path}:{exc.lineno}: {exc.msg}"
        )
        continue

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = alias.name

                if imported == "app" or imported.startswith("app."):
                    dependencies[module_name].add(imported)

        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imported = resolve_relative_import(
                    current_module=module_name,
                    current_path=file_path,
                    imported_module=node.module,
                    level=node.level,
                )
            else:
                imported = node.module or ""

            if imported == "app" or imported.startswith("app."):
                dependencies[module_name].add(imported)

                for alias in node.names:
                    possible_submodule = f"{imported}.{alias.name}"

                    if possible_submodule in known_modules:
                        dependencies[module_name].add(possible_submodule)


def module_exists(module_name: str) -> bool:
    if module_name in known_modules:
        return True

    return any(
        known.startswith(module_name + ".")
        for known in known_modules
    )


missing_imports: list[str] = []

for source_module, targets in dependencies.items():
    for target_module in sorted(targets):
        if not module_exists(target_module):
            missing_imports.append(
                f"{source_module} -> {target_module}"
            )


entrypoints = [
    module
    for module in ("main", "run_gui", "voice_assistant", "app.main")
    if module in known_modules
]

reachable: set[str] = set()
queue: deque[str] = deque(entrypoints)

while queue:
    module = queue.popleft()

    if module in reachable:
        continue

    reachable.add(module)

    for target in dependencies.get(module, set()):
        if target in known_modules and target not in reachable:
            queue.append(target)


candidate_unreachable = sorted(
    module
    for module in known_modules
    if module.startswith("app.")
    and module not in reachable
    and not module.endswith(".__init__")
)


basename_groups: dict[str, list[str]] = defaultdict(list)

for module_name, path in module_paths.items():
    if path.name != "__init__.py":
        basename_groups[path.name].append(module_name)

duplicate_names = {
    filename: modules
    for filename, modules in basename_groups.items()
    if len(modules) > 1
}


with (REPORTS_DIR / "internal_imports.txt").open(
    "w",
    encoding="utf-8",
) as report:
    for source_module in sorted(dependencies):
        report.write(f"{source_module}\n")

        for target_module in sorted(dependencies[source_module]):
            report.write(f"    -> {target_module}\n")


with (REPORTS_DIR / "missing_internal_imports.txt").open(
    "w",
    encoding="utf-8",
) as report:
    if missing_imports:
        report.write("\n".join(sorted(missing_imports)))
        report.write("\n")


with (REPORTS_DIR / "candidate_unreachable_modules.txt").open(
    "w",
    encoding="utf-8",
) as report:
    for module in candidate_unreachable:
        report.write(f"{module}\n")


with (REPORTS_DIR / "duplicate_module_names.txt").open(
    "w",
    encoding="utf-8",
) as report:
    for filename, modules in sorted(duplicate_names.items()):
        report.write(f"{filename}\n")

        for module in sorted(modules):
            report.write(f"    {module}\n")


with (REPORTS_DIR / "audit_syntax_errors.txt").open(
    "w",
    encoding="utf-8",
) as report:
    if syntax_errors:
        report.write("\n".join(syntax_errors))
        report.write("\n")


print("Mama AI dependency audit completed.")
print(f"Python modules scanned: {len(module_paths)}")
print(f"Missing internal imports: {len(missing_imports)}")
print(f"Candidate unreachable modules: {len(candidate_unreachable)}")
print(f"Duplicate filenames: {len(duplicate_names)}")
print(f"Syntax errors: {len(syntax_errors)}")
print(f"Reports saved in: {REPORTS_DIR}")