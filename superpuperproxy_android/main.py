"""
SuperPuperProxy — Android GUI wrapper
=====================================
Wraps the universal upstream-proxy adapter (HTTP / HTTPS / SOCKS5 -> plain
local HTTP proxy) in a tiny Kivy app so it can be packaged as an Android APK
(via buildozer) with its own icon and Start/Stop button.

Run this app on an Android TV box (or any Android device) sitting on the same
network as your YouTube device, or run it directly ON the YouTube box itself
if it can run APKs (most Android TV boxes can). Then point the YouTube
device's Wi-Fi proxy settings at this app's IP : LISTEN_PORT.

The bridge runs in a background thread with its own asyncio event loop, so
the UI thread stays responsive.
"""

import asyncio
import base64
import socket
import struct
import threading

from kivy.app import App
from kivy.clock import mainthread
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

# ── DEFAULTS (can be overridden from the UI) ─────────────────────────
UPSTREAM_TYPE = "socks5"          # "http" | "https" | "socks5"
UPSTREAM_HOST = "*.*.*.*"         # <-- your upstream proxy host
UPSTREAM_PORT = 1080
UPSTREAM_USER = ""
UPSTREAM_PASS = ""

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 8080
# ──────────────────────────────────────────────────────────────────────


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


def basic_auth_header(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Proxy-Authorization: Basic {token}\r\n"


class Bridge:
    """Runs the local HTTP-proxy <-> upstream-proxy adapter in its own thread."""

    def __init__(self, log_cb):
        self.log_cb = log_cb
        self._loop = None
        self._server = None
        self._thread = None

        self.upstream_type = UPSTREAM_TYPE
        self.upstream_host = UPSTREAM_HOST
        self.upstream_port = UPSTREAM_PORT
        self.upstream_user = UPSTREAM_USER
        self.upstream_pass = UPSTREAM_PASS
        self.listen_port = LISTEN_PORT

    # -- lifecycle -----------------------------------------------------
    def start(self, upstream_type, host, port, user, password, listen_port):
        if self._thread and self._thread.is_alive():
            return
        self.upstream_type = upstream_type
        self.upstream_host = host
        self.upstream_port = port
        self.upstream_user = user
        self.upstream_pass = password
        self.listen_port = listen_port
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)

    # -- internals ------------------------------------------------------
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
        self._server = await asyncio.start_server(self._handle, LISTEN_HOST, self.listen_port)
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "?"
        self.log_cb(
            f"Local HTTP proxy listening on {LISTEN_HOST}:{self.listen_port}\n"
            f"Set this on your YouTube device (Wi-Fi -> Proxy -> Manual):\n"
            f"   hostname = {local_ip}   port = {self.listen_port}\n"
            f"Upstream ({self.upstream_type.upper()}): {self.upstream_host}:{self.upstream_port}"
        )
        async with self._server:
            await self._server.serve_forever()

    # -- upstream connectors --------------------------------------------
    async def _connect_via_http_upstream(self, target_host, target_port, use_tls):
        if use_tls:
            import ssl
            ctx = ssl.create_default_context()
            reader, writer = await asyncio.open_connection(
                self.upstream_host, self.upstream_port, ssl=ctx, server_hostname=self.upstream_host
            )
        else:
            reader, writer = await asyncio.open_connection(self.upstream_host, self.upstream_port)

        req = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n"
        if self.upstream_user:
            req += basic_auth_header(self.upstream_user, self.upstream_pass)
        req += "Proxy-Connection: Keep-Alive\r\n\r\n"
        writer.write(req.encode())
        await writer.drain()

        status_line = await reader.readline()
        if b"200" not in status_line:
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

    async def _connect_via_socks5_upstream(self, target_host, target_port):
        reader, writer = await asyncio.open_connection(self.upstream_host, self.upstream_port)

        if self.upstream_user:
            writer.write(b"\x05\x02\x00\x02")
        else:
            writer.write(b"\x05\x01\x00")
        await writer.drain()

        chosen = await reader.readexactly(2)
        if chosen[0] != 0x05:
            writer.close()
            raise ConnectionError("Upstream is not a SOCKS5 proxy")

        method = chosen[1]
        if method == 0x02:
            u = self.upstream_user.encode()
            p = self.upstream_pass.encode()
            writer.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            await writer.drain()
            auth_resp = await reader.readexactly(2)
            if auth_resp[1] != 0x00:
                writer.close()
                raise ConnectionError("SOCKS5 upstream auth failed")
        elif method == 0xFF:
            writer.close()
            raise ConnectionError("SOCKS5 upstream: no acceptable auth method")

        try:
            packed_ip = socket.inet_aton(target_host)
            addr_bytes = b"\x01" + packed_ip
        except OSError:
            host_bytes = target_host.encode()
            addr_bytes = b"\x03" + bytes([len(host_bytes)]) + host_bytes

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
        await reader.readexactly(2)

        return reader, writer

    async def _open_tunnel(self, target_host, target_port):
        if self.upstream_type == "http":
            return await self._connect_via_http_upstream(target_host, target_port, use_tls=False)
        elif self.upstream_type == "https":
            return await self._connect_via_http_upstream(target_host, target_port, use_tls=True)
        elif self.upstream_type == "socks5":
            return await self._connect_via_socks5_upstream(target_host, target_port)
        raise ValueError(f"Unknown upstream type: {self.upstream_type!r}")

    # -- local plain-HTTP proxy handler ----------------------------------
    async def _handle(self, client_reader, client_writer):
        peer = client_writer.get_extra_info("peername")
        try:
            first_line = await client_reader.readline()
            if not first_line:
                client_writer.close()
                return
            try:
                method, target, _ver = first_line.decode("latin-1").strip().split(" ", 2)
            except ValueError:
                client_writer.close()
                return

            if method.upper() == "CONNECT":
                host, _, port_s = target.partition(":")
                port = int(port_s or "443")
                while True:
                    line = await client_reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break

                self.log_cb(f"CONNECT {host}:{port} (from {peer})")
                try:
                    up_reader, up_writer = await self._open_tunnel(host, port)
                except Exception as e:
                    self.log_cb(f"Upstream tunnel failed for {host}:{port} — {e}")
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await client_writer.drain()
                    client_writer.close()
                    return

                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()
                await asyncio.gather(
                    pipe(client_reader, up_writer),
                    pipe(up_reader, client_writer),
                )
            else:
                if target.startswith("http://"):
                    rest = target[len("http://"):]
                    host_port, _, path = rest.partition("/")
                    path = "/" + path
                else:
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

                self.log_cb(f"{method} http://{host}:{port}{path} (from {peer})")
                try:
                    up_reader, up_writer = await self._open_tunnel(host, port)
                except Exception as e:
                    self.log_cb(f"Upstream tunnel failed for {host}:{port} — {e}")
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await client_writer.drain()
                    client_writer.close()
                    return

                up_writer.write(f"{method} {path} HTTP/1.1\r\n".encode("latin-1"))
                up_writer.write(b"Connection: close\r\n")
                for h in headers:
                    up_writer.write(h.encode("latin-1"))
                up_writer.write(b"\r\n")
                await up_writer.drain()

                await asyncio.gather(
                    pipe(client_reader, up_writer),
                    pipe(up_reader, client_writer),
                )
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            self.log_cb(f"Connection error: {e}")
        finally:
            try:
                client_writer.close()
            except Exception:
                pass


class RootWidget(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=16, spacing=8, **kwargs)

        self.type_spinner = Spinner(
            text=UPSTREAM_TYPE,
            values=("http", "https", "socks5"),
            size_hint_y=None, height=44,
        )
        self.host_input = TextInput(text=UPSTREAM_HOST, multiline=False, hint_text="Upstream proxy host")
        self.port_input = TextInput(text=str(UPSTREAM_PORT), multiline=False, hint_text="Upstream proxy port")
        self.user_input = TextInput(text=UPSTREAM_USER, multiline=False, hint_text="Username (optional)")
        self.pass_input = TextInput(text=UPSTREAM_PASS, multiline=False, hint_text="Password (optional)", password=True)
        self.listen_input = TextInput(text=str(LISTEN_PORT), multiline=False, hint_text="Local proxy port (for TV box)")

        self.add_widget(Label(text="Upstream proxy type:", size_hint_y=None, height=24))
        self.add_widget(self.type_spinner)
        self.add_widget(Label(text="Upstream proxy host:", size_hint_y=None, height=24))
        self.add_widget(self.host_input)
        self.add_widget(Label(text="Upstream proxy port:", size_hint_y=None, height=24))
        self.add_widget(self.port_input)
        self.add_widget(Label(text="Username / Password (optional):", size_hint_y=None, height=24))
        self.add_widget(self.user_input)
        self.add_widget(self.pass_input)
        self.add_widget(Label(text="Local proxy port (set on YouTube device):", size_hint_y=None, height=24))
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
            upstream_type = self.type_spinner.text.strip().lower()
            host = self.host_input.text.strip()
            port = int(self.port_input.text.strip())
            user = self.user_input.text.strip()
            password = self.pass_input.text.strip()
            listen_port = int(self.listen_input.text.strip())
        except ValueError:
            self.log("Invalid port values.")
            return
        self.bridge.start(upstream_type, host, port, user, password, listen_port)
        self.log("Starting SuperPuperProxy...")

    def on_stop(self, _):
        self.bridge.stop()
        self.log("Stopped.")


class SuperPuperProxyApp(App):
    title = "SuperPuperProxy"

    def build(self):
        return RootWidget()


if __name__ == "__main__":
    SuperPuperProxyApp().run()
