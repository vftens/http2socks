"""
HTTP Proxy  ->  SOCKS5 bridge
==============================
Telegram Desktop uses:  HTTP proxy  (e.g. 1.2.3.4:8080)
Telegram Mobile uses:   SOCKS5      (this script, port 1080)

Set HTTP_PROXY_HOST and HTTP_PROXY_PORT to your current HTTP proxy values.
"""

import asyncio
import logging
import struct
import socket

# ── CONFIGURE HERE ────────────────────────────────────────────────
HTTP_PROXY_HOST = "45.81.227.97" # 127.0.0.1"   # <-- your HTTP proxy host
HTTP_PROXY_PORT = 8888           # <-- your HTTP proxy port

LISTEN_HOST = "0.0.0.0"         # listen on all interfaces
LISTEN_PORT = 1080               # SOCKS5 port for Telegram Mobile
# ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("http2socks")


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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


async def socks5_handshake(reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter) -> tuple[str, int]:
    """Parse SOCKS5 greeting + request, return (host, port)."""

    # Greeting
    header = await reader.readexactly(2)
    if header[0] != 0x05:
        raise ValueError(f"Not SOCKS5 (ver={header[0]})")
    nmethods = header[1]
    await reader.readexactly(nmethods)          # skip method list
    writer.write(b"\x05\x00")                  # choose NO AUTH
    await writer.drain()

    # Request
    req = await reader.readexactly(4)
    ver, cmd, _, atyp = req
    if ver != 0x05 or cmd != 0x01:             # only CONNECT
        writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
        raise ValueError(f"Unsupported cmd={cmd}")

    if atyp == 0x01:                            # IPv4
        raw = await reader.readexactly(4)
        host = socket.inet_ntoa(raw)
    elif atyp == 0x03:                          # domain
        n = (await reader.readexactly(1))[0]
        host = (await reader.readexactly(n)).decode()
    elif atyp == 0x04:                          # IPv6
        raw = await reader.readexactly(16)
        host = socket.inet_ntop(socket.AF_INET6, raw)
    else:
        raise ValueError(f"Unknown atyp={atyp}")

    port_raw = await reader.readexactly(2)
    port = struct.unpack("!H", port_raw)[0]

    return host, port


async def handle(client_r: asyncio.StreamReader,
                 client_w: asyncio.StreamWriter) -> None:
    peer = client_w.get_extra_info("peername")
    try:
        host, port = await socks5_handshake(client_r, client_w)
        log.info(f"CONNECT {host}:{port}  (from {peer[0]}:{peer[1]})")

        # Connect to HTTP proxy
        proxy_r, proxy_w = await asyncio.open_connection(
            HTTP_PROXY_HOST, HTTP_PROXY_PORT
        )

        # Send HTTP CONNECT
        connect_req = (
            f"CONNECT {host}:{port} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Proxy-Connection: keep-alive\r\n\r\n"
        )
        proxy_w.write(connect_req.encode())
        await proxy_w.drain()

        # Read HTTP response
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = await proxy_r.read(4096)
            if not chunk:
                break
            response += chunk

        if b"200" not in response.split(b"\r\n")[0]:
            status = response.split(b"\r\n")[0].decode(errors="replace")
            log.warning(f"HTTP proxy refused: {status}")
            client_w.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            client_w.close()
            proxy_w.close()
            return

        # Tell client: success
        client_w.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await client_w.drain()

        # Bidirectional pipe
        await asyncio.gather(
            pipe(client_r, proxy_w),
            pipe(proxy_r, client_w),
        )

    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        log.debug(f"Connection error from {peer}: {e}")
    finally:
        try:
            client_w.close()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
    local_ip = socket.gethostbyname(socket.gethostname())
    log.info(f"HTTP proxy:  {HTTP_PROXY_HOST}:{HTTP_PROXY_PORT}")
    log.info(f"SOCKS5 listening on  0.0.0.0:{LISTEN_PORT}")
    log.info(f"")
    log.info(f"  Set in Telegram Mobile:")
    log.info(f"    Type:   SOCKS5")
    log.info(f"    Server: {local_ip}")
    log.info(f"    Port:   {LISTEN_PORT}")
    log.info(f"")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
