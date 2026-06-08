# SuperPuperProxy for Android

This folder turns `SuperPuperProxy.py` (the universal HTTP/HTTPS/SOCKS5 ->
plain-HTTP proxy adapter for YouTube on Android TV) into an installable
Android app (`.apk`) with its own icon and a simple Start/Stop UI, built with
[Kivy](https://kivy.org/) + [Buildozer](https://buildozer.readthedocs.io/).

## Why this exists

Android TV YouTube boxes only support a plain, no-auth **HTTP** proxy in their
Wi-Fi settings. If your actual upstream proxy is SOCKS5, HTTPS, or an
authenticated HTTP proxy, the TV box can't use it directly.

SuperPuperProxy bridges the gap: it runs a small no-auth local HTTP proxy
server (the kind Android TV understands) and forwards everything through your
real upstream proxy of any supported type.

## Files

- `main.py` — Kivy GUI wrapper around the adapter. Lets you pick the upstream
  proxy type (`http` / `https` / `socks5`), host, port, optional
  username/password, and the local listen port — then Start/Stop the bridge
  from a background thread with its own asyncio event loop.
- `icon.png` — generated app icon (512×512, rounded, purple/orange).
- `buildozer.spec` — Buildozer build configuration (package name, permissions,
  icon path, target API levels, `arm64-v8a` only).

## Build the APK

Buildozer only runs on Linux (use WSL on Windows, or a Linux VM/container).

```bash
# 1. Install buildozer (inside WSL/Linux), e.g. in a venv
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install buildozer cython

# 2. From this `superpuperproxy_android/` directory, build a debug APK
buildozer -v android debug
```

The first run downloads the Android SDK/NDK (several GB) — it can take a
while. When it finishes, the APK appears in
`bin/superpuperproxy-1.0-arm64-v8a-debug.apk`.

> If you've already built `http2socks` via Buildozer in WSL, most system
> dependencies (SDK, NDK, JDK, build tools) are already cached and this build
> should be much faster — typically just a couple of minutes.

## Install

```bash
# with the device connected over USB and "USB debugging" enabled:
buildozer android deploy run logcat
```

…or copy the `.apk` from `bin/` to the device and tap it to install (enable
"Install unknown apps" first).

## Using the app

1. Run **SuperPuperProxy** — either on the Android TV box itself (if it can
   sideload APKs, most can), or on any Android device on the same LAN as the
   TV box.
2. Fill in:
   - **Upstream proxy type**: `http`, `https`, or `socks5`
   - **Upstream proxy host / port**: your real proxy address (e.g. the one
     you already use elsewhere — keep it private, don't share it!)
   - **Username / Password**: only if your upstream proxy requires auth
   - **Local proxy port**: the port the TV box will connect to (default `8080`)
3. Tap **Start**. The status box shows the device's local IP — that's the
   address you enter on the YouTube device.
4. On the YouTube/Android-TV device: **Settings → Network → Wi-Fi → (long-press
   your network) → Modify network → Advanced options → Proxy: Manual**
   - Proxy hostname = the IP shown in SuperPuperProxy's status box
   - Proxy port = the **local proxy port** you set (e.g. `8080`)
5. Open YouTube — its traffic now flows through your upstream proxy via
   SuperPuperProxy.
6. Tap **Stop** to shut the bridge down.

## Notes

- Requires `INTERNET` permission (already declared in `buildozer.spec`).
- Keep the app in the foreground/recent apps — Android may suspend background
  network sockets after a while. For an always-on bridge you'd want to convert
  it into a proper Android foreground `Service`
  (`android.permissions = FOREGROUND_SERVICE` is already requested as a
  starting point for that work).
- Never commit your real proxy address/credentials — keep `UPSTREAM_HOST` as
  `*.*.*.*` in the source and fill in the real value only in the running app's
  UI fields.
