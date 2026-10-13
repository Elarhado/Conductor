# Настройки

## Настройка плагина

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `python` | пусто (автопоиск `python3` → `python` → `py`) | явная команда Python 3.8+, если автопоиск не находит интерпретатор |

## `.conductor/config.json` (в проекте)

Указывайте только то, что меняете; остальное берётся по умолчанию.

```json
{
  "profile": "auto",
  "language_user": "ru",
  "language_internal": "en",
  "verify": {"max_rounds": 4, "gate": true, "max_gate_blocks": 3, "strict_numbers": true},
  "parallel": {"max_agents": 3},
  "forge": {"confirm": true, "skip_trivial": true},
  "codemap": {
    "max_files": 20000, "max_file_bytes": 1000000, "session_map_chars": 4000,
    "modules": {"net": ["Assets/Scripts/Net/*"]},
    "ignore": ["data/raw/*"]
  },
  "price_per_mtok": {
    "opus": {"in": 4.0, "out": 20.0}, "fable": {"in": 10.0, "out": 50.0},
    "sonnet": {"in": 3.0, "out": 15.0}, "haiku": {"in": 1.0, "out": 5.0}
  },
  "cache_read_factor": 0.1,
  "cache_write_factor": 1.25
}
```

| Ключ | Смысл |
|---|---|
| `profile` | research / build / analytics / auto — какой шаблон ТЗ брать по умолчанию |
| `verify.max_rounds` | максимум раундов проверки, затем открытое удаляется или помечается |
| `verify.gate` | Stop-хук не даёт закончить с непроверенными утверждениями |
| `verify.strict_numbers` | число или дата без `[Cn]` в финальном тексте блокирует выдачу |
| `parallel.max_agents` | сколько субагентов одновременно |
| `forge.confirm` | показывать ТЗ и спрашивать перед запуском |
| `codemap.modules` | ручная группировка файлов в модули (glob) |
| `price_per_mtok` | только для оценки в отчёте `/conductor:tokens`; сверяйте с актуальными ценами |

Цены Opus 5.5 ($4/$20) и Fable 5.1 ($10/$50) взяты из публикаций на сентябрь–октябрь 2026. Sonnet и Haiku указаны ориентировочно — проверьте актуальные значения на странице цен Anthropic.
