from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = BACKEND_DIR / "reports"
IMPORT_REPORT = REPORTS_DIR / "internal_imports.txt"

ACTIVE_MODULES_REPORT = REPORTS_DIR / "active_modules.txt"
ACTIVE_FILES_REPORT = REPORTS_DIR / "active_files.txt"


def read_dependency_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    current_module: str | None = None

    for raw_line in IMPORT_REPORT.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()

        if not line:
            continue

        if line.startswith("    -> "):
            if current_module is not None:
                target = line.replace("    -> ", "", 1).strip()
                graph[current_module].add(target)
        else:
            current_module = line.strip()
            graph.setdefault(current_module, set())

    return graph


def module_to_path(module_name: str) -> Path | None:
    parts = module_name.split(".")

    file_path = BACKEND_DIR.joinpath(*parts).with_suffix(".py")
    package_path = BACKEND_DIR.joinpath(*parts, "__init__.py")

    if file_path.exists():
        return file_path

    if package_path.exists():
        return package_path

    return None


def find_active_modules(
    graph: dict[str, set[str]],
    entrypoints: list[str],
) -> set[str]:
    active: set[str] = set()
    queue: deque[str] = deque(entrypoints)

    while queue:
        module = queue.popleft()

        if module in active:
            continue

        active.add(module)

        for dependency in graph.get(module, set()):
            if dependency not in active:
                queue.append(dependency)

    return active


def main() -> None:
    if not IMPORT_REPORT.exists():
        raise FileNotFoundError(
            "Run scripts\\audit_imports.py before this script."
        )

    graph = read_dependency_graph()

    possible_entrypoints = [
        "main",
        "run_gui",
        "voice_assistant",
        "app.main",
    ]

    entrypoints = [
        module
        for module in possible_entrypoints
        if module in graph
    ]

    active_modules = find_active_modules(graph, entrypoints)

    active_files: list[Path] = []

    for module in sorted(active_modules):
        module_path = module_to_path(module)

        if module_path is not None:
            active_files.append(module_path)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    ACTIVE_MODULES_REPORT.write_text(
        "\n".join(sorted(active_modules)) + "\n",
        encoding="utf-8",
    )

    ACTIVE_FILES_REPORT.write_text(
        "\n".join(
            str(path.relative_to(BACKEND_DIR))
            for path in sorted(active_files)
        )
        + "\n",
        encoding="utf-8",
    )

    print("Mama AI active-module report completed.")
    print(f"Entrypoints: {', '.join(entrypoints)}")
    print(f"Active modules: {len(active_modules)}")
    print(f"Active files found: {len(active_files)}")
    print(f"Report: {ACTIVE_MODULES_REPORT}")
    print(f"Files: {ACTIVE_FILES_REPORT}")


if __name__ == "__main__":
    main()