# Инструкции разработки 1С для Claude Code

Правила разработки этого проекта лежат в `AGENTS.md`. Читать его перед любой работой с BSL-кодом, метаданными, тестами и Merge Request / Pull Request.

@AGENTS.md

## Доступные навыки (Agent Skills)

Для решения типовых инженерных задач используйте соответствующие скиллы из каталога `skills/`:

- `skills/bsl-code-review/SKILL.md` - комплексное код-ревью BSL-кода, аудит diff в MR/PR, классификация дефектов и confidence score.
- `skills/bsl-diagnostics/SKILL.md` - статический анализ BSL Language Server / синтакс-контроль с фильтрацией по строкам diff.
- `skills/query-optimizer/SKILL.md` - аудит и оптимизация запросов 1С: устранение подзапросов, временные таблицы, индексация, параметры ВТ.
- `skills/form-designer/SKILL.md` - проектирование структуры и модулей управляемых форм, программная модификация в `ПриСозданииНаСервере`.
- `skills/yaxunit-tests/SKILL.md` - создание тестов YAxUnit, методы AAA, регистрация в `ИсполняемыеСценарии`, фабрики данных.
- `skills/vanessa-bdd/SKILL.md` - разработка BDD-сценариев Vanessa Automation, база 1569 шагов, поиск и валидация .feature.
- `skills/edt-metadata/SKILL.md` - создание и модификация метаданных EDT (*.mdo, Form.form), валидация и исправление UUID.
- `skills/bsp-api/SKILL.md` - справочник API БСП (2624 метода, контексты клиент/сервер), валидация вызовов до написания кода.
- `skills/bsp-patterns/SKILL.md` - прикладные сценарии БСП (38 тем, регламентные задания, длительные операции, печать, права).
- `skills/worklog-tracker/SKILL.md` - ведение анализа задачи, сквозного журнала сессий (worklog) и архитектурных решений (ADR).

## Окружение и локальные настройки

- Параметры проекта (`{PREFIX}`, `{PLATFORM_VERSION}`, `{USES_BSP}`, `{LOCK_MODE}`) считываются из `project-profile.md`.
- Личные настройки разработчика (`workflow/local.md`, `.mcp.json`, каталоги `.claude` и `.cursor`) в репозиторий не коммитятся (см. `.gitignore`).
- Свои дополнения к правилам и сопоставление MCP-ролей держать в `workflow/local.md`.
