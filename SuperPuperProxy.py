"""
SuperPuperProxy — universal upstream-proxy adapter for YouTube on Android TV
=============================================================================

Проблема:
  Приложение YouTube на Android-приставке (Android TV box) НЕ умеет
  подключаться напрямую к произвольному прокси (HTTP / HTTPS / SOCKS5)
  с логином/паролем — Android поддерживает в настройках Wi-Fi только
  простой HTTP-прокси (host:port, без авторизации).

Решение:
  SuperPuperProxy поднимает у вас в локальной сети ОБЫЧНЫЙ HTTP-прокси
  (без пароля), а сам внутри подключается к ЛЮБОМУ вышестоящему прокси:
      • HTTP    (CONNECT-туннель, с логином/паролем или без)
      • HTTPS   (CONNECT-туннель поверх TLS, с логином/паролем или без)
      • SOCKS5  (с логином/паролем или без)

  Таким образом сигнал из любого прокси "конвертируется" в простой
  локальный HTTP-прокси, который Android TV приставка спокойно понимает
  и который можно прописать в настройках Wi-Fi приставки как:
      Proxy hostname:  <IP компьютера в локальной сети>
      Proxy port:      8080   (LISTEN_PORT ниже)

Использование:
  1. Заполните блок "CONFIGURE HERE" — тип и адрес вашего прокси.
  2. Запустите:  python SuperPuperProxy.py
  3. На приставке Android TV: Settings -> Network -> Wi-Fi ->
     (долгое нажатие на сеть) -> Modify network -> Advanced options ->
     Proxy: Manual -> Proxy hostname = IP этого компьютера,
     Proxy port = LISTEN_PORT.
  4. Откройте YouTube на приставке — трафик пойдёт через ваш прокси.
"""

import asyncio
import base64
import logging
import socket
import struct

# ── CONFIGURE HERE ────────────────────────────────────────────────────
# Тип вышестоящего прокси: "http", "https" или "socks5"
UPSTREAM_TYPE = "socks5"            # <-- "http" | "https" | "socks5"

UPSTREAM_HOST = "*.*.*.*"           # <-- адрес вашего прокси (IPv4)
UPSTREAM_PORT = 1080                # <-- порт вашего прокси

# Логин/пароль, если прокси требует авторизацию (иначе оставьте пустыми)
UPSTREAM_USER = ""
UPSTREAM_PASS = ""

# Локальный HTTP-прокси, который будет "видеть" приставка Android TV.
# Пропишите IP этого компьютера в локальной сети + этот порт в
# настройках Wi-Fi-прокси на приставке.
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8080
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SuperPuperProxy")


# ──────────────────────────────────────────────────────────────────────
# Общие утилиты
# ──────────────────────────────────────────────────────────────────────

async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, label: str = "") -> None:
    """Перекачивает байты из reader в writer, пока не закончится поток."""
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def basic_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Proxy-Authorization: Basic {token}\r\n"


# ──────────────────────────────────────────────────────────────────────
# Подключение к вышестоящему прокси (HTTP / HTTPS / SOCKS5)
# Возвращает уже готовый (reader, writer) — "туннель" до целевого host:port
# ──────────────────────────────────────────────────────────────────────

async def connect_via_http_upstream(target_host: str, target_port: int, use_tls: bool):
    """CONNECT-туннель через HTTP или HTTPS прокси."""
    if use_tls:
        import ssl
        ctx = ssl.create_default_context()
        reader, writer = await asyncio.open_connection(
            UPSTREAM_HOST, UPSTREAM_PORT, ssl=ctx, server_hostname=UPSTREAM_HOST
        )
    else:
        reader, writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)

    req = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n"
    if UPSTREAM_USER:
        req += basic_auth_header(UPSTREAM_USER, UPSTREAM_PASS)
    req += "Proxy-Connection: Keep-Alive\r\n\r\n"

    writer.write(req.encode())
    await writer.drain()

    # Читаем ответ построчно до пустой строки
    status_line = await reader.readline()
    if b"200" not in status_line:
        # дочитываем заголовки, чтобы не оставлять "грязный" сокет
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        writer.close()
        raise ConnectionError(f"Upstream HTTP proxy refused CONNECT: {status_line.strip()}")

    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break

    return reader, writer


async def connect_via_socks5_upstream(target_host: str, target_port: int):
    """Устанавливает TCP-туннель к target_host:target_port через SOCKS5."""
    reader, writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)

    # ── greeting ──
    if UPSTREAM_USER:
        writer.write(b"\x05\x02\x00\x02")     # methods: no-auth, user/pass
    else:
        writer.write(b"\x05\x01\x00")         # methods: no-auth
    await writer.drain()

    chosen = await reader.readexactly(2)
    if chosen[0] != 0x05:
        writer.close()
        raise ConnectionError("Upstream is not a SOCKS5 proxy")

    method = chosen[1]
    if method == 0x02:                         # username/password auth required
        u = UPSTREAM_USER.encode()
        p = UPSTREAM_PASS.encode()
        writer.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        await writer.drain()
        auth_resp = await reader.readexactly(2)
        if auth_resp[1] != 0x00:
            writer.close()
            raise ConnectionError("SOCKS5 upstream auth failed")
    elif method == 0xFF:
        writer.close()
        raise ConnectionError("SOCKS5 upstream: no acceptable auth method")

    # ── connect request ──
    try:
        packed_ip = socket.inet_aton(target_host)
        addr_bytes = b"\x01" + packed_ip                       # IPv4
    except OSError:
        host_bytes = target_host.encode()
        addr_bytes = b"\x03" + bytes([len(host_bytes)]) + host_bytes  # domain name

    writer.write(b"\x05\x01\x00" + addr_bytes + struct.pack(">H", target_port))
    await writer.drain()

    reply = await reader.readexactly(4)
    if reply[1] != 0x00:
        writer.close()
        raise ConnectionError(f"SOCKS5 upstream CONNECT failed, code={reply[1]}")

    atyp = reply[3]
    if atyp == 0x01:
        await reader.readexactly(4)
    elif atyp == 0x03:
        n = (await reader.readexactly(1))[0]
        await reader.readexactly(n)
    elif atyp == 0x04:
        await reader.readexactly(16)
    await reader.readexactly(2)  # bound port

    return reader, writer


async def open_tunnel(target_host: str, target_port: int):
    """Унифицированная точка: открыть туннель к цели через выбранный upstream."""
    if UPSTREAM_TYPE == "http":
        return await connect_via_http_upstream(target_host, target_port, use_tls=False)
    elif UPSTREAM_TYPE == "https":
        return await connect_via_http_upstream(target_host, target_port, use_tls=True)
    elif UPSTREAM_TYPE == "socks5":
        return await connect_via_socks5_upstream(target_host, target_port)
    else:
        raise ValueError(f"Unknown UPSTREAM_TYPE={UPSTREAM_TYPE!r}")


# ──────────────────────────────────────────────────────────────────────
# Локальный HTTP-прокси сервер (то, что видит приставка Android TV)
# ──────────────────────────────────────────────────────────────────────

async def handle_client(client_reader: asyncio.StreamReader,
                         client_writer: asyncio.StreamWriter) -> None:
    peer = client_writer.get_extra_info("peername")
    try:
        first_line = await client_reader.readline()
        if not first_line:
            client_writer.close()
            return

        try:
            method, target, _version = first_line.decode("latin-1").strip().split(" ", 2)
        except ValueError:
            client_writer.close()
            return

        if method.upper() == "CONNECT":
            # HTTPS: CONNECT host:port HTTP/1.1
            host, _, port_s = target.partition(":")
            port = int(port_s or "443")

            # дочитываем и отбрасываем заголовки CONNECT-запроса
            while True:
                line = await client_reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break

            log.info("CONNECT %s:%s  <- %s", host, port, peer)
            try:
                up_reader, up_writer = await open_tunnel(host, port)
            except Exception as exc:
                log.warning("Upstream tunnel failed for %s:%s — %s", host, port, exc)
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                return

            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()

            await asyncio.gather(
                pipe(client_reader, up_writer, "client->upstream"),
                pipe(up_reader, client_writer, "upstream->client"),
            )

        else:
            # Обычный HTTP-запрос: GET http://host[:port]/path HTTP/1.1
            if target.startswith("http://"):
                rest = target[len("http://"):]
                host_port, _, path = rest.partition("/")
                path = "/" + path
            else:
                # относительный путь — берём Host из заголовков
                host_port, path = "", target

            host, _, port_s = host_port.partition(":")
            port = int(port_s) if port_s else 80

            headers = []
            while True:
                line = await client_reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode("latin-1")
                if not host and decoded.lower().startswith("host:"):
                    hv = decoded.split(":", 1)[1].strip()
                    h, _, p = hv.partition(":")
                    host, port = h, int(p) if p else 80
                if not decoded.lower().startswith(("proxy-connection:", "proxy-authorization:")):
                    headers.append(decoded)

            if not host:
                client_writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                return

            log.info("%s http://%s:%s%s  <- %s", method, host, port, path, peer)
            try:
                up_reader, up_writer = await open_tunnel(host, port)
            except Exception as exc:
                log.warning("Upstream tunnel failed for %s:%s — %s", host, port, exc)
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                return

            request_line = f"{method} {path} HTTP/1.1\r\n"
            up_writer.write(request_line.encode("latin-1"))
            up_writer.write(("Connection: close\r\n").encode("latin-1"))
            for h in headers:
                up_writer.write(h.encode("latin-1"))
            up_writer.write(b"\r\n")
            await up_writer.drain()

            await asyncio.gather(
                pipe(client_reader, up_writer, "client->upstream"),
                pipe(up_reader, client_writer, "upstream->client"),
            )

    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    except Exception as exc:
        log.exception("Unhandled error from %s: %s", peer, exc)
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)

    log.info("=" * 70)
    log.info("SuperPuperProxy запущен")
    log.info("Локальный HTTP-прокси слушает на: %s", addrs)
    log.info("Вышестоящий прокси (%s): %s:%s", UPSTREAM_TYPE.upper(), UPSTREAM_HOST, UPSTREAM_PORT)
    log.info("")
    log.info("На приставке Android TV пропишите в Wi-Fi -> Proxy -> Manual:")
    log.info("    Proxy hostname = <IP этого компьютера в локальной сети>")
    log.info("    Proxy port     = %s", LISTEN_PORT)
    log.info("=" * 70)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановлено пользователем (Ctrl+C)")
