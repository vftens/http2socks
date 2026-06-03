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
HTTP_PROXY_HOST = "45.81.227.97"  # your HTTP proxy host
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

## How it works

1. Accepts a SOCKS5 `CONNECT` handshake (no auth, IPv4 / IPv6 / domain).
2. Opens a TCP connection to the upstream HTTP proxy.
3. Sends an HTTP `CONNECT` request for the target host:port.
4. On `200 Connection established`, splices the two sockets together bidirectionally.

## License

MIT — see [LICENSE](LICENSE).
