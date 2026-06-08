"""
http2socks — Android GUI wrapper
================================
Wraps the asyncio HTTP-proxy -> SOCKS5 bridge in a tiny Kivy app so it can be
packaged as an Android APK (via buildozer) with its own icon and a Start/Stop
button. The bridge itself runs in a background thread with its own asyncio
event loop, so the UI thread stays responsive.

Edit HTTP_PROXY_HOST / HTTP_PROXY_PORT below before building, or change them
from the UI fields and press "Start".
"""

import asyncio
import socket
import struct
import threading

from kivy.app import App
from kivy.clock import mainthread
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

# ── DEFAULTS (can be overridden from the UI) ─────────────────────
HTTP_PROXY_HOST = "*.*.*.*"      # <-- your HTTP proxy host
HTTP_PROXY_PORT = 8888
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 1080
# ─────────────────────────────────────────────────────────────────


async def pipe(reader, writer):
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


async def socks5_handshake(reader, writer):
    header = await reader.readexactly(2)
    if header[0] != 0x05:
        raise ValueError(f"Not SOCKS5 (ver={header[0]})")
    nmethods = header[1]
    await reader.readexactly(nmethods)
    writer.write(b"\x05\x00")
    await writer.drain()

    req = await reader.readexactly(4)
    ver, cmd, _, atyp = req
    if ver != 0x05 or cmd != 0x01:
        writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
        raise ValueError(f"Unsupported cmd={cmd}")

    if atyp == 0x01:
        raw = await reader.readexactly(4)
        host = socket.inet_ntoa(raw)
    elif atyp == 0x03:
        n = (await reader.readexactly(1))[0]
        host = (await reader.readexactly(n)).decode()
    elif atyp == 0x04:
        raw = await reader.readexactly(16)
        host = socket.inet_ntop(socket.AF_INET6, raw)
    else:
        raise ValueError(f"Unknown atyp={atyp}")

    port_raw = await reader.readexactly(2)
    port = struct.unpack("!H", port_raw)[0]
    return host, port


class Bridge:
    """Runs the SOCKS5<->HTTP bridge server in its own thread + event loop."""

    def __init__(self, log_cb):
        self.log_cb = log_cb
        self._loop = None
        self._server = None
        self._thread = None
        self.proxy_host = HTTP_PROXY_HOST
        self.proxy_port = HTTP_PROXY_PORT
        self.listen_port = LISTEN_PORT

    # -- lifecycle -------------------------------------------------
    def start(self, proxy_host, proxy_port, listen_port):
        if self._thread and self._thread.is_alive():
            return
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.listen_port = listen_port
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)

    # -- internals --------------------------------------------------
    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            self.log_cb(f"Stopped: {e}")
        finally:
            self._loop.close()
            self._loop = None

    async def _serve(self):
        self._server = await asyncio.start_server(
            self._handle, LISTEN_HOST, self.listen_port
        )
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "?"
        self.log_cb(
            f"SOCKS5 listening on {LISTEN_HOST}:{self.listen_port}\n"
            f"Local IP (set this in Telegram Mobile): {local_ip}\n"
            f"Upstream HTTP proxy: {self.proxy_host}:{self.proxy_port}"
        )
        async with self._server:
            await self._server.serve_forever()

    async def _handle(self, client_r, client_w):
        peer = client_w.get_extra_info("peername")
        try:
            host, port = await socks5_handshake(client_r, client_w)
            self.log_cb(f"CONNECT {host}:{port} (from {peer})")

            proxy_r, proxy_w = await asyncio.open_connection(
                self.proxy_host, self.proxy_port
            )

            connect_req = (
                f"CONNECT {host}:{port} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Proxy-Connection: keep-alive\r\n\r\n"
            )
            proxy_w.write(connect_req.encode())
            await proxy_w.drain()

            response = b""
            while b"\r\n\r\n" not in response:
                chunk = await proxy_r.read(4096)
                if not chunk:
                    break
                response += chunk

            if b"200" not in response.split(b"\r\n")[0]:
                client_w.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
                client_w.close()
                proxy_w.close()
                return

            client_w.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_w.drain()

            await asyncio.gather(
                pipe(client_r, proxy_w),
                pipe(proxy_r, client_w),
            )
        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            self.log_cb(f"Connection error: {e}")
        finally:
            try:
                client_w.close()
            except Exception:
                pass


class RootWidget(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=16, spacing=10, **kwargs)

        self.host_input = TextInput(text=HTTP_PROXY_HOST, multiline=False, hint_text="HTTP proxy host")
        self.port_input = TextInput(text=str(HTTP_PROXY_PORT), multiline=False, hint_text="HTTP proxy port")
        self.listen_input = TextInput(text=str(LISTEN_PORT), multiline=False, hint_text="SOCKS5 listen port")

        self.add_widget(Label(text="HTTP proxy host:"))
        self.add_widget(self.host_input)
        self.add_widget(Label(text="HTTP proxy port:"))
        self.add_widget(self.port_input)
        self.add_widget(Label(text="SOCKS5 listen port (Telegram Mobile):"))
        self.add_widget(self.listen_input)

        btn_row = BoxLayout(size_hint_y=None, height=48, spacing=10)
        self.start_btn = Button(text="Start", on_press=self.on_start)
        self.stop_btn = Button(text="Stop", on_press=self.on_stop)
        btn_row.add_widget(self.start_btn)
        btn_row.add_widget(self.stop_btn)
        self.add_widget(btn_row)

        self.status = Label(text="Idle.", halign="left", valign="top")
        self.status.bind(size=self.status.setter("text_size"))
        self.add_widget(self.status)

        self.bridge = Bridge(self.log)

    @mainthread
    def log(self, msg):
        self.status.text = msg

    def on_start(self, _):
        try:
            host = self.host_input.text.strip()
            port = int(self.port_input.text.strip())
            listen_port = int(self.listen_input.text.strip())
        except ValueError:
            self.log("Invalid host/port values.")
            return
        self.bridge.start(host, port, listen_port)
        self.log("Starting bridge...")

    def on_stop(self, _):
        self.bridge.stop()
        self.log("Stopped.")


class Http2SocksApp(App):
    title = "http2socks"

    def build(self):
        return RootWidget()


if __name__ == "__main__":
    Http2SocksApp().run()
