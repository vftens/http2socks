# http2socks for Android

This folder turns the desktop `http2socks.py` bridge into an installable Android
app (`.apk`) with its own icon and a simple Start/Stop UI, built with
[Kivy](https://kivy.org/) + [Buildozer](https://buildozer.readthedocs.io/).

## Files

- `main.py` — Kivy GUI wrapper. Runs the same SOCKS5 ⇄ HTTP-CONNECT bridge as
  the desktop script, but in a background thread with editable host/port
  fields and Start/Stop buttons.
- `icon.png` — generated app icon (512×512, rounded, blue).
- `buildozer.spec` — Buildozer build configuration (package name, permissions,
  icon path, target API levels).

## Build the APK

Buildozer only runs on Linux (use WSL on Windows, or a Linux VM/container).

```bash
# 1. Install buildozer (inside WSL/Linux)
pip install --user buildozer cython

# 2. From this `android/` directory, build a debug APK
buildozer -v android debug
```

The first run downloads the Android SDK/NDK (several GB) — it can take a
while. When it finishes, the APK appears in `bin/http2socks-1.0-debug.apk`.

## Install on your phone

```bash
# with the phone connected over USB and "USB debugging" enabled:
buildozer android deploy run
```

…or just copy the `.apk` from `bin/` to the phone and tap it to install
(enable "Install unknown apps" for your file manager/browser first).

## Using the app

1. Open **http2socks** on your phone.
2. Enter your **HTTP proxy host/port** (the upstream proxy Telegram Desktop
   already uses) and the **SOCKS5 listen port** (default `1080`).
3. Tap **Start**. The status box shows the phone's local IP — that's what
   you'd normally enter in *another* device's Telegram Mobile SOCKS5 settings.
   To use the proxy *on the same phone*, point apps that support SOCKS5 at
   `127.0.0.1:1080`.
4. Tap **Stop** to shut the bridge down.

## Notes

- Requires `INTERNET` permission (already declared in `buildozer.spec`).
- Keep the app in the foreground/recent apps — Android may suspend background
  network sockets after a while. For a always-on proxy you'd want to convert
  the bridge into a proper Android foreground `Service`
  (`android.permissions = FOREGROUND_SERVICE` is already requested as a
  starting point for that work).
- Edit the `HTTP_PROXY_HOST` / `HTTP_PROXY_PORT` defaults at the top of
  `main.py` before building if you want them pre-filled.
