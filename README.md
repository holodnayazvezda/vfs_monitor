# VFS CDP Monitor

Минимальный рабочий монитор VFS Global для маршрута `rus/ru/hun`.

Идея:

- Chrome запускается как обычный браузер с Chrome DevTools Protocol на порту `9222`.
- Пользователь вручную логинится в VFS и вручную проходит Cloudflare/CAPTCHA.
- Если `VFS_PASSWORD` задан, сервис может сам открыть форму входа и заполнить email/пароль. CAPTCHA и отправку формы делает пользователь.
- Сервис перехватывает один настоящий запрос `CheckIsSlotAvailable` из браузера.
- Дальше Python каждые 2 минуты выполняет `fetch()` внутри этой же вкладки Chrome и получает JSON-ответы.
- Результат печатается в консоль и отправляется в Telegram.
- Если сессия протухла или VFS начал отдавать ошибки по всем категориям, сервис просит перелогиниться и снова ждёт один настоящий запрос из UI.

Сервис не обходит CAPTCHA, не кликает Cloudflare и не отправляет форму входа вместо пользователя.

## Что проверяется

Файл конфигурации: `config/vfs_target.yaml`

```yaml
country_code: rus
mission_code: hun
center_code: HUNRUS38

categories:
  RH: Captured category from VFS UI
  VS_1_2: Other (Not a Tourism) / Иные цели
  VS_1_1: Tourism / Туризм
```

## Ручной запуск

### 1. Установка

```bash
cd /Users/dany/coding/projects/vfs-global/vfs-cdp-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example config/.env
```

Заполни `config/.env`:

```env
TG_TOKEN=...
OWNER_CHAT_ID=...
VFS_LOGIN_USER=your-vfs-email@example.com
VFS_PASSWORD=your-vfs-password
```

### 2. Запуск Chrome

```bash
./scripts/start_chrome_cdp.sh
```

В открытом Chrome:

- открой VFS;
- прими cookies;
- если включен login assist, дождись заполнения email/пароля;
- пройди Cloudflare/CAPTCHA вручную и нажми кнопку входа сам;
- открой форму записи;
- один раз вызови проверку категории, чтобы VFS отправил `CheckIsSlotAvailable`.

### 3. Запуск сервиса

В другом терминале:

```bash
source .venv/bin/activate
python -m vfs_cdp_monitor.service \
  --interval 120
```

Если свежих заголовков ещё нет, сервис напишет в консоль/Telegram, что ждёт реальный `CheckIsSlotAvailable`.
После этого просто вызови проверку категории в UI VFS один раз.

Отдельно проверить только автоподготовку формы входа можно так:

```bash
python -m vfs_cdp_monitor.login_assist_cli
```

Она откроет/использует вкладку VFS, попробует нажать `Записаться на прием`, заполнит email/пароль и остановится. CAPTCHA и кнопку входа нужно пройти вручную.

## Docker

Docker-контейнер запускает только Python-сервис. Chrome остаётся на хосте, потому что логин и CAPTCHA нужно проходить руками в обычном браузере.

### 1. Запусти Chrome на хосте

На macOS:

```bash
cd /Users/dany/coding/projects/vfs-global/vfs-cdp-monitor
CDP_ADDRESS=0.0.0.0 CDP_ALLOW_ORIGINS='*' ./scripts/start_chrome_cdp.sh
```

Важно: Docker должен видеть CDP Chrome по `host.docker.internal:9222`.
Для обычного ручного запуска без Docker используй `./scripts/start_chrome_cdp.sh`, чтобы CDP слушал только `127.0.0.1`.

### 2. Подготовь `.env` для Docker Compose

В корне проекта создай `.env`:

```env
TG_TOKEN=...
OWNER_CHAT_ID=...
VFS_LOGIN_USER=your-vfs-email@example.com
VFS_PASSWORD=your-vfs-password
CDP_URL=http://host.docker.internal:9222
```

### 3. Запусти сервис

```bash
docker compose up --build
```

Дальше в Chrome вручную логинишься и вызываешь один запрос категории. Контейнер поймает `authorize/clientSource`, сохранит их в `config/browser_session.local.json` и начнёт мониторинг.

## Остановка

Ручной запуск:

```bash
Ctrl+C
```

Docker:

```bash
docker compose down
```

Chrome можно закрыть обычным способом.

## Поведение при ошибках

Если VFS начинает отдавать `401`, `403`, `429201` по всем категориям или Chrome недоступен, сервис:

1. отправляет сообщение в Telegram;
2. открывает/ожидает Chrome с CDP;
3. если есть `VFS_PASSWORD`, пытается открыть форму входа и заполнить email/пароль;
4. ждёт один настоящий `CheckIsSlotAvailable`;
5. сохраняет свежие заголовки;
6. продолжает мониторинг.
