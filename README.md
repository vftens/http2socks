# http2socks

A lightweight async bridge that exposes a **SOCKS5** listener and tunnels all connections through an upstream **HTTP proxy** via `CONNECT`.

## Use case

Telegram Desktop works fine with an HTTP proxy, but Telegram Mobile only accepts SOCKS5.  
Run this script on the same machine — point Telegram Mobile at it as a SOCKS5 proxy.

## Requirements

- Python 3.11+
- No third-party dependencies

## Configuration

Edit the constants at the top of `http2socks.py`:

```python
HTTP_PROXY_HOST = "*"  # your HTTP proxy host
HTTP_PROXY_PORT = 8888             # your HTTP proxy port

LISTEN_HOST = "0.0.0.0"           # listen on all interfaces
LISTEN_PORT = 1080                 # SOCKS5 port
```

## Usage

```bash
python http2socks.py
```

On startup the script prints the local IP and port to enter in Telegram Mobile:

```
Settings → Data and Storage → Proxy → Add Proxy
  Type:   SOCKS5
  Server: <your local IP>
  Port:   1080
```

## Android version

A packaged Android app (APK) with its own icon and a Start/Stop UI lives in
[`android/`](android/) — see [`android/README_ANDROID.md`](android/README_ANDROID.md)
for build/install instructions (Kivy + Buildozer).

### How to build the .apk

Buildozer (the tool that packages the Kivy app into an `.apk`) only runs on
Linux — on Windows you need **WSL** (Windows Subsystem for Linux) or a Linux
VM/container. The first build downloads the Android SDK/NDK (several GB), so
it can take a long time; later builds reuse the cache and are much faster.

```bash
# 1. Open a WSL/Linux shell and go to the android/ folder
cd android

# 2. Create a virtual environment and install the build tools
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install buildozer cython

# 3. Build a debug APK (this also auto-downloads SDK/NDK on first run)
buildozer -v android debug
```

System packages you'll likely need on a fresh Ubuntu/WSL (install with
`sudo apt install ...`): `python3-pip`, `python3-venv`, `git`, `zip unzip`,
`openjdk-17-jdk-headless`, `autoconf automake libtool m4`, `gcc g++ make
python3-dev`, `zlib1g-dev libssl-dev libbz2-dev libreadline-dev
libsqlite3-dev liblzma-dev tk-dev`.

When the build finishes, the APK appears in
`android/bin/http2socks-1.0-arm64-v8a-debug.apk`. Copy it to your phone and
tap to install (enable "Install unknown apps" first), or run
`buildozer android deploy run` with the phone connected over USB.

See [`android/README_ANDROID.md`](android/README_ANDROID.md) for full details.

## How it works

1. Accepts a SOCKS5 `CONNECT` handshake (no auth, IPv4 / IPv6 / domain).
2. Opens a TCP connection to the upstream HTTP proxy.
3. Sends an HTTP `CONNECT` request for the target host:port.
4. On `200 Connection established`, splices the two sockets together bidirectionally.

## License

MIT — see [LICENSE](LICENSE).
