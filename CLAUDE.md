# CLAUDE.md — форк remnawave-bedolaga-telegram-bot

Это **форк AirShadow** апстрим-проекта BEDOLAGA-DEV, а не самостоятельный продукт.
Файл держим коротким: полная процедура обновления живёт в инфраструктурной репе.

## ⚠️ Хостинг кода — GitLab (переезд 2026-08-10)

- `origin` → **`git@gitlab.com:airshadow/telegram-bot.git`** — приватная группа
  `gitlab.com/airshadow`, ключ `~/.ssh/gitlab`, пользователь `@airerik`.
- `github-dead` → мёртвый GitHub-remote, **пушить туда нельзя**. Аккаунт `Air-Erik`
  забанен 2026-06-02, сменивший его `ErnsetAirapetov` — 2026-08-10; приватные репы
  обоих недоступны даже на чтение.
- `upstream` → `https://github.com/BEDOLAGA-DEV/remnawave-bedolaga-telegram-bot.git`
  — **остался на GitHub**. Он публичный и читается анонимно, поэтому синк с апстримом
  работает как раньше.
- CLI — **`glab`** (`C:\CLI\glab\glab.exe`), не `gh`. PR здесь называются **MR**
  (`glab mr create`). GitLab API дёргать экономно: это последний оставшийся хостинг.

## Ветки

- **`airshadow-prod`** — деплой-ветка, из неё control-plane собирает прод.
  Содержимое = `upstream/main` + локальные патчи, не принятые в апстрим.
- `main` — зеркало апстрима, руками не трогаем.
- Работа идёт **через ветку + MR** в `airshadow-prod`, не прямыми коммитами.

## Валидация

```bash
uv run --with tzdata pytest -q
```

`--with tzdata` на Windows обязателен — без него валидатор `TIMEZONE` падает прямо
на импорте.

## Процедура обновления

Синк с апстримом, разрешение конфликтов, список локальных патчей и деплой на CP —
всё в инфраструктурной репе: `Air-Shadow/.claude/commands/update-services.md`.
Не изобретать процедуру заново, там описаны известные грабли.
