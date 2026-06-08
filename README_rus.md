# http2socks

Лёгкий асинхронный мост, который поднимает локальный **SOCKS5**-сервер и
туннелирует все соединения через вышестоящий **HTTP-прокси** с помощью
метода `CONNECT`.

## Зачем это нужно

Telegram Desktop прекрасно работает с HTTP-прокси, а вот Telegram Mobile
понимает только SOCKS5. Запустите этот скрипт на той же машине — и укажите
его в Telegram Mobile как SOCKS5-прокси.

## Требования

- Python 3.11+
- Никаких сторонних зависимостей

## Настройка

Отредактируйте константы в начале файла `http2socks.py`:

```python
HTTP_PROXY_HOST = "*"  # хост вашего HTTP-прокси
HTTP_PROXY_PORT = 8888             # порт вашего HTTP-прокси

LISTEN_HOST = "0.0.0.0"           # слушать на всех интерфейсах
LISTEN_PORT = 1080                 # порт SOCKS5
```

## Использование

```bash
python http2socks.py
```

При запуске скрипт выводит локальный IP и порт, которые нужно указать в
Telegram Mobile:

```
Настройки → Данные и память → Прокси → Добавить прокси
  Тип:    SOCKS5
  Сервер: <ваш локальный IP>
  Порт:   1080
```

## Версия для Android

Собранное Android-приложение (APK) со своей иконкой и кнопками Start/Stop
лежит в [`android/`](android/) — инструкции по сборке/установке (Kivy +
Buildozer) см. в [`android/README_ANDROID.md`](android/README_ANDROID.md).

## Как это работает

1. Принимает рукопожатие SOCKS5 `CONNECT` (без авторизации, IPv4 / IPv6 / домен).
2. Открывает TCP-соединение с вышестоящим HTTP-прокси.
3. Отправляет HTTP-запрос `CONNECT` на целевой host:port.
4. При ответе `200 Connection established` сшивает оба сокета в обе стороны.

## Дополнительно: SuperPuperProxy

В этом же репозитории есть `SuperPuperProxy.py` — универсальный адаптер
прокси для просмотра YouTube на Android TV приставках. Он превращает любой
вышестоящий прокси (HTTP, HTTPS или SOCKS5, с авторизацией или без) в
простой локальный HTTP-прокси без пароля, который понимает Android TV.
Android-версия с GUI и иконкой лежит в
[`superpuperproxy_android/`](superpuperproxy_android/) — см.
[`superpuperproxy_android/README_ANDROID.md`](superpuperproxy_android/README_ANDROID.md).

## Лицензия

MIT — см. [LICENSE](LICENSE).
