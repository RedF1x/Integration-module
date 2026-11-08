# Integration-module

Модуль интеграции Jira для Ламарта.

Текущий этап: Django-каркас, PostgreSQL, запуск через Docker Compose, проверочная страница `/jira/`, pytest и Ruff.

Модели Jira, авторизация практикантов, синхронизация и API пока не реализованы.

## Требования

- Git.
- Установленный и запущенный Docker Desktop с Linux-контейнерами.
- Свободные локальные порты 8000 и 5432.

## Первый запуск

Клонируйте репозиторий и перейдите в папку проекта:

```powershell
git clone https://github.com/RedF1x/Integration-module.git
cd Integration-module
```

Создайте собственный файл настроек:

```powershell
Copy-Item .env.example .env
```

Если `.env` уже существует, сохраните свои настройки — повторно копировать файл не нужно.

В `.env`:

- Задайте локальный пароль в `POSTGRES_PASSWORD`.
- Укажите этот же пароль в `DATABASE_URL`.
- Замените заглушку `SECRET_KEY` собственным случайным ключом.
- `DEBUG=True` используйте только для разработки.

Для простоты локальной настройки используйте пароль из латинских букв и цифр: специальные символы в адресе базы требуют URL-кодирования.

Соберите образ:

```powershell
docker compose build
```

Сгенерируйте ключ:

```powershell
docker compose run --rm --no-deps web python -c "import secrets; print(secrets.token_hex(32))"
```

Скопируйте полученную строку в `SECRET_KEY` своего `.env`. Не публикуйте `.env` и секретный ключ.

Запустите проект:

```powershell
docker compose up -d
docker compose ps
docker compose logs --tail=40 web
```

При запуске Django дожидается готовности PostgreSQL и применяет миграции.

Откройте http://127.0.0.1:8000/jira/ — появится сообщение «Модуль интеграции Jira запущен.».

## Проверки

```powershell
docker compose exec web python manage.py check
docker compose exec web python -m pytest -q
docker compose exec web python -m ruff check .
```

Текущий тест проверяет маршрут `/jira/` и ответ проверочной страницы. Проверок прав и моделей пока нет.

## После изменения кода или зависимостей

Код копируется в образ при сборке. Чтобы применить изменения:

```powershell
docker compose up --build -d
```

## Остановка

```powershell
docker compose down
```

Данные PostgreSQL сохраняются в Docker volume `postgres_data`. Не добавляйте `-v`, если хотите сохранить базу.

Значения `POSTGRES_USER`, `POSTGRES_PASSWORD` и `POSTGRES_DB` используются при первоначальном создании базы. Изменение `.env` не меняет пароль уже существующей базы автоматически.

## Структура

- `standalone/` — настройки самостоятельного Django-проекта.
- `jira_integration/` — приложение интеграции.
- `Dockerfile` — сборка приложения.
- `docker-compose.yml` — запуск Django и PostgreSQL.
- `.env.example` — образец настроек без настоящих секретов.
- `requirements.txt` — зависимости.
- `pyproject.toml` — настройки pytest и Ruff.

При запуске Django из Windows база доступна по `127.0.0.1:5432`. В контейнере Django использует адрес `db:5432`, заданный через Compose.

## Совместная работа

Работа ведётся в отдельных ветках. Изменения попадают в `main` через Pull Request с ревью второго бэкендера и успешными проверками.

Модели и миграции создаёт Бэкенд Б. Контракт данных согласуют оба бэкендера.

Текущая конфигурация использует сервер разработки Django и предназначена для локальной разработки.