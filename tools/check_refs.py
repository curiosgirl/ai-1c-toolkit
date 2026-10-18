"""
Проверка целостности пакета ai-onec-toolkit.

1. Ссылки на файлы в документации существуют: имена в обратных кавычках и пути
   от каталогов пакета (skills/, rules/, workflow/, agents/, tools/, docs/) в любом месте текста,
   включая блоки кода.
2. AGENTS.md - реестр для агентов: в нем упомянут каждый навык skills/*/SKILL.md
   и каждый субагент agents/onec-*.md. README.md - витрина для людей: в нем упомянут каждый навык.
3. У каждого субагента есть адаптеры в .cursor/agents/ и .claude/agents/ с одинаковым description.

Использование (из корня репозитория):
    python tools/check_refs.py

Код возврата: 0 - проблем нет, 1 - найдены проблемы.
"""

import os
import re
import subprocess
import sys

DOC_SUFFIXES = (".md", ".mdc")
REF_SUFFIXES = r"(?:md|mdc|py|json|jsonl)"
BACKTICK_REF = re.compile(r"`([\w./-]+\." + REF_SUFFIXES + r")`")
PACKAGE_PATH = re.compile(r"(?<![\w./-])((?:skills|rules|workflow|agents|tools|docs)/[\w./-]+\." + REF_SUFFIXES + r")\b")
PLACEHOLDER = re.compile(r"[{}<>*]")

# Личные файлы разработчика: по замыслу отсутствуют в репозитории.
LOCAL_FILES = {".mcp.json", ".cursor/mcp.json", "workflow/local.md", "local.md"}

# Ссылки на файлы других проектов (атрибуция источника).
EXTERNAL_REFS = {
    ("rules/form-patterns.md", "docs/form-patterns.md"),
    ("skills/edt-metadata/references/ai-edt-facades.md", "docs/tools/README.ru.md"),
}

AGENTS_REGISTRY = "AGENTS.md"
HUMAN_CATALOG = "README.md"
ADAPTER_DIRS = (".cursor/agents", ".claude/agents")


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", check=True)
    return [f for f in result.stdout.splitlines() if os.path.exists(f)]


def normalize(path: str) -> str:
    return os.path.normpath(path).replace("\\", "/")


def check_references(files: list[str]) -> list[str]:
    tracked = set(files)
    basenames = {os.path.basename(f) for f in files}
    problems = []
    docs = [f for f in files if f.endswith(DOC_SUFFIXES) or f == ".cursorrules"]
    for doc in docs:
        base = os.path.dirname(doc)
        with open(doc, encoding="utf-8") as fh:
            for num, line in enumerate(fh, 1):
                refs = set(BACKTICK_REF.findall(line)) | set(PACKAGE_PATH.findall(line))
                for ref in sorted(refs):
                    if PLACEHOLDER.search(ref) or ref in LOCAL_FILES or (doc, ref) in EXTERNAL_REFS:
                        continue
                    if {normalize(ref), normalize(os.path.join(base, ref))} & tracked:
                        continue
                    if "/" not in ref and ref in basenames:
                        continue
                    problems.append(f"{doc}:{num}: нет файла `{ref}`")
    return problems


def check_registry(files: list[str]) -> list[str]:
    skills = sorted(f for f in files if re.fullmatch(r"skills/[^/]+/SKILL\.md", f))
    agents = sorted(f for f in files if re.fullmatch(r"agents/onec-[^/]+\.md", f))
    expected = {AGENTS_REGISTRY: skills + agents, HUMAN_CATALOG: skills}
    problems = []
    for registry_file, paths in expected.items():
        with open(registry_file, encoding="utf-8") as fh:
            registry = fh.read()
        for path in paths:
            if f"`{path}`" not in registry:
                problems.append(f"{registry_file}: не зарегистрирован `{path}`")
    return problems


def read_description(path: str) -> str | None:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("description:"):
                return line.split(":", 1)[1].strip()
    return None


def check_adapters(files: list[str]) -> list[str]:
    problems = []
    agents = {os.path.basename(f) for f in files if re.fullmatch(r"agents/onec-[^/]+\.md", f)}
    adapters = {d: {os.path.basename(f) for f in files if f.startswith(d + "/")} for d in ADAPTER_DIRS}
    for name in sorted(agents | set().union(*adapters.values())):
        if name not in agents:
            problems.append(f"agents/{name}: нет описания для адаптера")
            continue
        descriptions = {}
        for d in ADAPTER_DIRS:
            if name not in adapters[d]:
                problems.append(f"{d}/{name}: нет адаптера для agents/{name}")
            else:
                descriptions[d] = read_description(f"{d}/{name}")
        if len(set(descriptions.values())) > 1:
            problems.append(f"{name}: description различается в {', '.join(ADAPTER_DIRS)}")
    return problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    files = tracked_files()
    problems = check_references(files) + check_registry(files) + check_adapters(files)
    for problem in problems:
        print(problem)
    if problems:
        print(f"\nНайдено проблем: {len(problems)}")
        return 1
    print("OK - ссылки, реестр и адаптеры в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main())
