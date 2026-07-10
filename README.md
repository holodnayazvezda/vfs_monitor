# VFS CDP Monitor

Монитор слотов VFS Global для Венгрии в Санкт-Петербурге (`rus/ru/hun`, `HUNRUS38`).

Сервис работает через обычный Chrome с включенным Chrome DevTools Protocol. CAPTCHA не обходится: пользователь проходит ее вручную. После входа сервис сам выполняет `CheckIsSlotAvailable` внутри залогиненной вкладки Chrome раз в 2 минуты и отправляет результат в Telegram.

## Что проверяется

Файл: `config/vfs_target.yaml`

```yaml
route: rus/ru/hun
country_code: rus
mission_code: hun
center_code: HUNRUS38

categories:
  VS_1_2: Other (Not a Tourism) / Иные цели
  VS_1_1: Tourism / Туризм
```

## Как это работает

1. Chrome запускается с CDP на `127.0.0.1:9222`.
2. Если сессии нет, сервис открывает VFS, принимает cookies, переходит к логину и заполняет email/password из `config/.env`.
3. Сервис ждет `30` секунд, чтобы пользователь вручную прошел CAPTCHA.
4. Сервис нажимает кнопку `Войти`.
5. После входа сервис берет из браузера `sessionStorage.JWT` и `sessionStorage.csk_str`.
6. Каждые `120` секунд сервис выполняет `fetch()` внутри вкладки Chrome и проверяет слоты.
7. Результат печатается в лог и отправляется в Telegram.

Сервис не обходит CAPTCHA и не кликает Cloudflare.

## Настройка

```bash
cd /Users/dany/coding/projects/vfs-global/vfs-cdp-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example config/.env
```

Заполни `config/.env`:

```env
TG_TOKEN=telegram-bot-token
OWNER_CHAT_ID=telegram-chat-id
VFS_LOGIN_USER=your-vfs-email@example.com
VFS_PASSWORD=your-vfs-password
```

`config/.env` находится в `.gitignore`.

## Ручной запуск

1. Запусти Chrome с CDP:

```bash
./scripts/start_chrome_cdp.sh
```

2. В другом терминале запусти сервис:

```bash
source .venv/bin/activate
python -m vfs_cdp_monitor.service --interval 120 --login-submit-wait 30
```

3. Если откроется CAPTCHA, пройди ее руками. Сервис сам нажмет `Войти` после 30 секунд.

Остановка ручного режима:

```bash
Ctrl+C
```

## Проверить только логин

```bash
source .venv/bin/activate
python -m vfs_cdp_monitor.login_assist_cli
```

Команда откроет/использует вкладку VFS, примет cookies, перейдет к логину и заполнит email/password. CAPTCHA и отправка формы остаются ручным шагом.

## Запуск как macOS-сервис

Файл LaunchAgent лежит в проекте: `launchd/com.dany.vfs-cdp-monitor.plist`.

Установить LaunchAgent:

```bash
mkdir -p ~/Library/LaunchAgents
cp launchd/com.dany.vfs-cdp-monitor.plist ~/Library/LaunchAgents/
```

Запустить или перезапустить сервис:

```bash
launchctl bootstrap gui/$(id -u) /Users/dany/Library/LaunchAgents/com.dany.vfs-cdp-monitor.plist
launchctl kickstart -k gui/$(id -u)/com.dany.vfs-cdp-monitor
```

Если агент уже был загружен и нужно переустановить:

```bash
launchctl bootout gui/$(id -u) /Users/dany/Library/LaunchAgents/com.dany.vfs-cdp-monitor.plist
launchctl bootstrap gui/$(id -u) /Users/dany/Library/LaunchAgents/com.dany.vfs-cdp-monitor.plist
```

Проверить статус:

```bash
launchctl print gui/$(id -u)/com.dany.vfs-cdp-monitor
```

Остановить:

```bash
launchctl bootout gui/$(id -u) /Users/dany/Library/LaunchAgents/com.dany.vfs-cdp-monitor.plist
```

Логи:

```text
data/service.log
data/service.err.log
```

## Docker

Docker запускает только Python-сервис. Chrome остается на хосте, потому что CAPTCHA нужно проходить руками.

1. Запусти Chrome на хосте так, чтобы контейнер видел CDP:

```bash
CDP_ADDRESS=0.0.0.0 CDP_ALLOW_ORIGINS='*' ./scripts/start_chrome_cdp.sh
```

2. Создай `.env` в корне проекта:

```env
TG_TOKEN=telegram-bot-token
OWNER_CHAT_ID=telegram-chat-id
VFS_LOGIN_USER=your-vfs-email@example.com
VFS_PASSWORD=your-vfs-password
CDP_URL=http://host.docker.internal:9222
```

3. Запусти:

```bash
docker compose up --build
```

Остановка:

```bash
docker compose down
```

## Поведение при ошибках

Если браузерная сессия пропала:

1. сервис отправит сообщение в Telegram;
2. откроет VFS-вкладку или Chrome;
3. заполнит логин и пароль;
4. даст `30` секунд на ручную CAPTCHA;
5. нажмет `Войти`;
6. продолжит проверки каждые `120` секунд.

Если VFS временно отвечает `429`, сервис не перелогинивается сразу, а ждет следующий интервал.
