# Changelog

## 1.0.0 — 2026-10-13
- Оркестратор `conduct`: триаж, ТЗ по шаблонам (research/build/analytics/general), подтверждение 1–4, маршрутизация по моделям, дисциплина токенов.
- Круговая верификация `verify`: реестр утверждений, независимые проверяющие, повтор только изменённого, лимит раундов, Stop-гейт.
- Карта проекта `codemap`: инкрементальная индексация по хукам, карточки модулей, `impact`.
- Журнал токенов `tokens`: по моделям и агентам.
- 9 субагентов: scout, reader, finder, formatter, cartographer (Haiku); builder, analyst, fact-checker, code-verifier (Sonnet).
- Проверено: `claude plugin validate --strict` (манифест, маркетплейс, агенты, скиллы), 11 юнит-тестов, живые прогоны в Claude Code 2.1.296 (хуки SessionStart/PostToolUse/Stop/SubagentStop; полный цикл analyst → fact-checker → render).
