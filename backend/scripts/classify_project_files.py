from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
REPORTS_DIR = BACKEND_DIR / "reports"

ACTIVE_FILES_REPORT = REPORTS_DIR / "active_files.txt"

FOLDER_SUMMARY_REPORT = REPORTS_DIR / "folder_activity_summary.txt"
FULLY_INACTIVE_REPORT = REPORTS_DIR / "fully_inactive_folders.txt"
INACTIVE_FILES_REPORT = REPORTS_DIR / "inactive_files.txt"
DYNAMIC_IMPORT_REPORT = REPORTS_DIR / "dynamic_import_usage.txt"


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)

        if parent:
            return f"{parent}.{node.attr}"

        return node.attr

    return ""


def top_level_group(file_path: Path) -> str:
    relative = file_path.relative_to(APP_DIR)

    if len(relative.parts) == 1:
        return "(app root)"

    return relative.parts[0]


def main() -> None:
    if not ACTIVE_FILES_REPORT.exists():
        raise FileNotFoundError(
            "reports\\active_files.txt does not exist. "
            "Run scripts\\list_active_modules.py first."
        )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    active_files: set[Path] = set()

    for line in ACTIVE_FILES_REPORT.read_text(
        encoding="utf-8"
    ).splitlines():
        line = line.strip()

        if line:
            active_files.add((BACKEND_DIR / line).resolve())

    all_files = sorted(
        path.resolve()
        for path in APP_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )

    folder_files: dict[str, list[Path]] = defaultdict(list)
    folder_active: dict[str, list[Path]] = defaultdict(list)
    folder_inactive: dict[str, list[Path]] = defaultdict(list)

    for file_path in all_files:
        group = top_level_group(file_path)

        folder_files[group].append(file_path)

        if file_path in active_files:
            folder_active[group].append(file_path)
        else:
            folder_inactive[group].append(file_path)

    summary_lines: list[str] = []
    fully_inactive_folders: list[str] = []
    inactive_files: list[str] = []

    for group in sorted(folder_files):
        total = len(folder_files[group])
        active = len(folder_active[group])
        inactive = len(folder_inactive[group])

        summary_lines.append(
            f"{group}: total={total}, active={active}, inactive={inactive}"
        )

        if active == 0 and group != "(app root)":
            fully_inactive_folders.append(f"app\\{group}")

        for file_path in sorted(folder_inactive[group]):
            inactive_files.append(
                str(file_path.relative_to(BACKEND_DIR))
            )

    dynamic_import_lines: list[str] = []

    for file_path in all_files:
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
        except (UnicodeDecodeError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            function_name = dotted_name(node.func)

            if function_name not in {
                "__import__",
                "importlib.import_module",
                "import_module",
            }:
                continue

            imported_value = "<dynamic expression>"

            if node.args:
                first_argument = node.args[0]

                if isinstance(first_argument, ast.Constant):
                    if isinstance(first_argument.value, str):
                        imported_value = first_argument.value

            relative_path = file_path.relative_to(BACKEND_DIR)

            dynamic_import_lines.append(
                f"{relative_path}:{node.lineno}: "
                f"{function_name}({imported_value})"
            )

    FOLDER_SUMMARY_REPORT.write_text(
        "\n".join(summary_lines) + "\n",
        encoding="utf-8",
    )

    FULLY_INACTIVE_REPORT.write_text(
        "\n".join(fully_inactive_folders) + "\n",
        encoding="utf-8",
    )

    INACTIVE_FILES_REPORT.write_text(
        "\n".join(inactive_files) + "\n",
        encoding="utf-8",
    )

    DYNAMIC_IMPORT_REPORT.write_text(
        "\n".join(sorted(dynamic_import_lines)) + "\n",
        encoding="utf-8",
    )

    print("Mama AI project classification completed.")
    print(f"Application Python files: {len(all_files)}")
    print(f"Active application files: {len(active_files)}")
    print(f"Fully inactive folders: {len(fully_inactive_folders)}")
    print(f"Dynamic import calls: {len(dynamic_import_lines)}")
    print(f"Reports saved in: {REPORTS_DIR}")


if __name__ == "__main__":
    main()