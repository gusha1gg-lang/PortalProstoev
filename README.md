# PortalProstoev

Портал учёта простоев по вине ИТ-компании для промышленного сектора: регистрация простоев,
классификация вины ИТ, конструктор объединённых простоев, расчёт потерь и SLA, дашборды и KPI,
управление инцидентами и RCA, отчётность для руководства и заказчика.

## Технологический стек
- **Язык + фреймворк:** Python 3.12+ + Django 6.x
- **Интерфейс:** Django Templates + HTMX, графики Chart.js (без React)
- **Админка/CRUD:** Django Admin
- **БД приложения:** PostgreSQL + Django ORM
- **Источник простоев:** Oracle DB (второй уровень), read-only через `python-oracledb`
- **ITIL-тикеты:** OMNITRACKER
- **Аутентификация:** ADFS (`django-auth-adfs`), маппинг групп AD → роли
- **Тесты:** pytest + pytest-django
- **Инфра:** Docker + docker-compose

Стек выбран сознательно простым: приоритет — понятность и сопровождаемость, а не «модность».

## Среды и развёртывание
| | Разработка (сейчас) | Прод (позже) |
|---|---|---|
| Хост | Windows + WSL2 (Ubuntu) | Oracle Linux-сервер в корпоративной доменной сети |
| Oracle DB | недоступна | доступна (read-only) |
| OMNITRACKER | недоступен | доступен через API |
| ADFS / домен | недоступен | доступен (вход сотрудников) |

**Ключевое требование:** проект разрабатывается и запускается локально в WSL **без доступа** к
корпоративным ресурсам. Все внешние интеграции работают в **mock-режиме**, включаемом через `.env`.
При переносе на прод те же адаптеры переключаются на реальные системы без изменения логики и шаблонов.

Флаги окружения:
```
INTEGRATION_MODE=mock        # mock | live   (Oracle DB, OMNITRACKER)
AUTH_MODE=dev                # dev  | adfs   (вход: dev-логин | ADFS)
DATABASE_URL=...             # локальный PostgreSQL (порт 5433)
POSTGRES_*                   # параметры БД, см. .env.example
```

## Структура проекта
```
PortalProstoev/
├─ manage.py
├─ config/              # настройки (base.py / dev.py / prod.py)
├─ apps/
│  ├─ accounts/         # вход и роли
│  ├─ catalog/          # справочники (предприятия, цеха, участки, агрегаты, категории вины)
│  ├─ downtimes/        # простои + кейсы (объединение) + журналы изменений
│  ├─ sla/              # потери, доступность, MTTR/MTBF и договоры SLA
│  ├─ integrations/     # Oracle, OMNITRACKER (mock / live), импорт простоев
│  ├─ reports/          # дашборды и отчёты
│  └─ notifications/    # уведомления и эскалации (email)
├─ static/              # стили и локальная библиотека графиков
├─ docs/                # документация рядом с кодом
├─ tests/
├─ docker-compose.yml
└─ .env.example
```

## Быстрый старт (разработка в WSL)
```bash
# 1. Настройки
cp .env.example .env

# 2. Зависимости
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 3. Локальный PostgreSQL (порт 5433 — 5432 занят другими проектами)
docker compose up -d

# 4. Структура БД
./.venv/bin/python manage.py migrate

# 5. Администратор и данные (один раз)
./.venv/bin/python manage.py createsuperuser
./.venv/bin/python manage.py seed_catalog       # справочники
./.venv/bin/python manage.py seed_downtimes     # демо-простои
./.venv/bin/python manage.py seed_sla           # демо-договоры SLA
./.venv/bin/python manage.py seed_notifications # демо-правила уведомлений
./.venv/bin/python manage.py seed_users         # демо-пользователи по ролям
# (необязательно) импорт простоев из источника в mock-режиме
./.venv/bin/python manage.py import_oracle

# 6. Запуск
./.venv/bin/python manage.py runserver
```
Открыть: http://127.0.0.1:8000/ — портал попросит **войти** (страница входа).
В разработке вход обычный, логин/пароль. Админ из шага 5, демо-пользователи — из `seed_users`
(пароль `DevPortal2026!`): `operator`, `specialist`, `it_manager`, `management`.
Дашборд — http://127.0.0.1:8000/, отчёт по потерям — /sla/, SLA-отчёт — /reports/sla/,
журнал уведомлений — /notifications/, админка — /admin/.
Подробно — в [`docs/каркас.md`](docs/каркас.md) и [`docs/модуль-accounts.md`](docs/модуль-accounts.md).

## Принципы разработки
- Мок-режим обязателен: проект собирается и работает без доступа в домен.
- Секреты только в `.env` / `.env.example`.
- Деньги и длительности считаются только на сервере.
- Импорт из Oracle идемпотентен (без дублей).
- Бизнес-логика — в `services.py`, не в шаблонах.

## Документация проекта
- [`project.md`](project.md) — полное описание проекта, стек, функции, бизнес-правила.
- [`AGENTS.MD`](AGENTS.MD) — правила работы агента, соглашения и техрешения.
- `docs/каркас.md` — как устроен каркас проекта (Этап 1).
- `docs/модуль-catalog.md` — справочники и роли (Этап 2).
- `docs/модуль-downtimes.md` — простои, кейсы и журналы изменений (этапы 3–4).
- `docs/модуль-sla.md` — потери, доступность, MTTR/MTBF и штрафы SLA (Этап 5).
- `docs/модуль-integrations.md` — импорт из Oracle и тикеты OMNITRACKER, mock/live (Этап 6).
- `docs/модуль-reports.md` — дашборд, KPI, SLA-отчёт и выгрузка (Этап 7).
- `docs/модуль-notifications.md` — уведомления и эскалации по email (Этап 8).
- `docs/модуль-accounts.md` — вход, роли и заготовка ADFS (Этап 9).
- `docs/источник-данных-oracle.md` — структура источника простоев.
- `docs/план.md` — план разработки по этапам.

## Правила ведения проекта
- **`README.md` и `AGENTS.MD` обновляются при каждом изменении**, затрагивающем запуск, стек,
  переменные окружения, модули или правила. Это часть Definition of Done.
- Документация коммитится вместе с кодом в одном изменении.

## Репозиторий
- GitHub: https://github.com/gusha1gg-lang/PortalProstoev
