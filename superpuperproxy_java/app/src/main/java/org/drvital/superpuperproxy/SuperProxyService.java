package org.drvital.superpuperproxy;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.util.Base64;
import android.util.Log;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * SuperPuperProxy — universal upstream-proxy adapter.
 *
 * Runs a plain, no-auth local HTTP proxy server that Android TV boxes
 * can use via Wi-Fi proxy settings.  Internally bridges every connection
 * through the configured upstream proxy, which can be:
 *   • HTTP   — TCP socket + CONNECT request (optional Basic auth)
 *   • HTTPS  — TLS socket + CONNECT request (optional Basic auth)
 *   • SOCKS5 — SOCKS5 handshake + CONNECT (optional user/pass auth)
 *
 * Architecture: one ServerSocket thread + one CachedThreadPool for
 * per-connection handling.  Each connection spawns two relay threads
 * (client→upstream, upstream→client) and waits for both to finish.
 */
public class SuperProxyService extends Service {

    static final String TAG          = "SuperProxySvc";
    static final String CHANNEL_ID   = "spp_channel";

    static final String ACTION_START   = "org.drvital.superpuperproxy.START";
    static final String ACTION_STOP    = "org.drvital.superpuperproxy.STOP";

    static final String EXTRA_UP_TYPE   = "up_type";    // "http"|"https"|"socks5"
    static final String EXTRA_UP_HOST   = "up_host";
    static final String EXTRA_UP_PORT   = "up_port";
    static final String EXTRA_UP_USER   = "up_user";
    static final String EXTRA_UP_PASS   = "up_pass";
    static final String EXTRA_LISTEN_PORT = "listen_port";

    static final String BROADCAST_STATUS = "org.drvital.superpuperproxy.STATUS";
    static final String EXTRA_STATUS     = "status";

    private String upType;
    private String upHost;
    private int    upPort;
    private String upUser;
    private String upPass;
    private int    listenPort;

    private ServerSocket    serverSocket;
    private ExecutorService executor;
    private volatile boolean running = false;

    // ── lifecycle ──────────────────────────────────────────────────────

    @Override public void onCreate()  { super.onCreate(); createNotificationChannel(); }
    @Override public IBinder onBind(Intent i) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) return START_NOT_STICKY;
        if (ACTION_START.equals(intent.getAction())) {
            upType     = intent.getStringExtra(EXTRA_UP_TYPE);
            upHost     = intent.getStringExtra(EXTRA_UP_HOST);
            upPort     = intent.getIntExtra(EXTRA_UP_PORT, 1080);
            upUser     = intent.getStringExtra(EXTRA_UP_USER);
            upPass     = intent.getStringExtra(EXTRA_UP_PASS);
            listenPort = intent.getIntExtra(EXTRA_LISTEN_PORT, 8080);
            startForeground(1, buildNotification("Local HTTP proxy on port " + listenPort));
            startServer();
        } else if (ACTION_STOP.equals(intent.getAction())) {
            stopServer();
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    // ── server ────────────────────────────────────────────────────────

    private void startServer() {
        executor = Executors.newCachedThreadPool();
        running  = true;
        executor.submit(() -> {
            try {
                serverSocket = new ServerSocket(listenPort);
                broadcast("✅ Local HTTP proxy on port " + listenPort +
                          "\nUpstream (" + upType.toUpperCase() + "): " + upHost + ":" + upPort +
                          "\n\nOn your Android TV box set Wi-Fi proxy:\n  Hostname: <this device IP>\n  Port: " + listenPort);
                while (running) {
                    Socket client = serverSocket.accept();
                    executor.submit(() -> handleClient(client));
                }
            } catch (IOException e) {
                if (running) broadcast("❌ Server error: " + e.getMessage());
            }
        });
    }

    private void stopServer() {
        running = false;
        close(serverSocket);
        if (executor != null) executor.shutdownNow();
        broadcast("Stopped.");
    }

    // ── per-connection handler ────────────────────────────────────────

    private void handleClient(Socket client) {
        Socket upstream = null;
        try {
            InputStream  cin  = client.getInputStream();
            OutputStream cout = client.getOutputStream();

            // ── parse first request line ────────────────────────────
            String firstLine = readLine(cin);
            if (firstLine == null || firstLine.isEmpty()) return;

            String[] parts = firstLine.split(" ", 3);
            if (parts.length < 2) return;
            String method = parts[0].toUpperCase();
            String target = parts[1];

            // ── read and collect headers ────────────────────────────
            List<String> headers = new ArrayList<>();
            String line;
            String hostHeader = null;
            while (!(line = readLine(cin)).isEmpty()) {
                String lower = line.toLowerCase();
                if (lower.startsWith("host:"))
                    hostHeader = line.substring(5).trim();
                if (!lower.startsWith("proxy-connection:") &&
                    !lower.startsWith("proxy-authorization:"))
                    headers.add(line);
            }

            if ("CONNECT".equals(method)) {
                // ── HTTPS tunnel ────────────────────────────────────
                String host; int port;
                int colon = target.lastIndexOf(':');
                if (colon > 0) {
                    host = target.substring(0, colon);
                    port = Integer.parseInt(target.substring(colon + 1));
                } else { host = target; port = 443; }

                upstream = openTunnel(host, port);
                cout.write("HTTP/1.1 200 Connection Established\r\n\r\n".getBytes("ISO-8859-1"));
                cout.flush();

            } else {
                // ── plain HTTP request ──────────────────────────────
                String host; int port; String path;
                if (target.startsWith("http://")) {
                    String rest = target.substring(7);
                    int slash = rest.indexOf('/');
                    String hostPort = slash >= 0 ? rest.substring(0, slash) : rest;
                    path = slash >= 0 ? rest.substring(slash) : "/";
                    int colon = hostPort.lastIndexOf(':');
                    if (colon > 0) { host = hostPort.substring(0, colon); port = Integer.parseInt(hostPort.substring(colon+1)); }
                    else           { host = hostPort; port = 80; }
                } else if (hostHeader != null) {
                    path = target;
                    int colon = hostHeader.lastIndexOf(':');
                    if (colon > 0) { host = hostHeader.substring(0, colon); port = Integer.parseInt(hostHeader.substring(colon+1)); }
                    else           { host = hostHeader; port = 80; }
                } else {
                    cout.write("HTTP/1.1 400 Bad Request\r\n\r\n".getBytes("ISO-8859-1"));
                    cout.flush(); return;
                }

                upstream = openTunnel(host, port);
                OutputStream uout = upstream.getOutputStream();

                // forward request
                uout.write((method + " " + path + " HTTP/1.1\r\n").getBytes("ISO-8859-1"));
                uout.write("Connection: close\r\n".getBytes("ISO-8859-1"));
                for (String h : headers)
                    uout.write((h + "\r\n").getBytes("ISO-8859-1"));
                uout.write("\r\n".getBytes("ISO-8859-1"));
                uout.flush();
            }

            // ── bidirectional relay ─────────────────────────────────
            final Socket up = upstream;
            Thread t1 = new Thread(() -> relay(cin,        sockOut(up), client, up));
            Thread t2 = new Thread(() -> relay(sockIn(up), cout,        up, client));
            t1.start(); t2.start();
            t1.join();  t2.join();

        } catch (Exception e) {
            Log.w(TAG, "Client error: " + e.getMessage());
        } finally {
            close(client);
            close(upstream);
        }
    }

    /** Helpers to unwrap checked IOException from lambdas. */
    private static OutputStream sockOut(Socket s) {
        try { return s.getOutputStream(); } catch (IOException e) { throw new RuntimeException(e); }
    }
    private static InputStream sockIn(Socket s) {
        try { return s.getInputStream(); } catch (IOException e) { throw new RuntimeException(e); }
    }

    // ── upstream tunnel factories ─────────────────────────────────────

    /** Opens a ready-to-use TCP tunnel to targetHost:targetPort via the configured upstream proxy. */
    private Socket openTunnel(String targetHost, int targetPort) throws IOException {
        switch (upType.toLowerCase()) {
            case "http":   return tunnelViaHttpProxy(targetHost, targetPort, false);
            case "https":  return tunnelViaHttpProxy(targetHost, targetPort, true);
            case "socks5": return tunnelViaSocks5(targetHost, targetPort);
            default: throw new IOException("Unknown upstream type: " + upType);
        }
    }

    /** HTTP or HTTPS upstream proxy via CONNECT. */
    private Socket tunnelViaHttpProxy(String targetHost, int targetPort, boolean tls)
            throws IOException {
        Socket sock;
        if (tls) {
            SSLSocket ssl = (SSLSocket) SSLSocketFactory.getDefault()
                    .createSocket(upHost, upPort);
            ssl.startHandshake();
            sock = ssl;
        } else {
            sock = new Socket(upHost, upPort);
        }
        InputStream  in  = sock.getInputStream();
        OutputStream out = sock.getOutputStream();

        StringBuilder req = new StringBuilder();
        req.append("CONNECT ").append(targetHost).append(':').append(targetPort).append(" HTTP/1.1\r\n");
        req.append("Host: ").append(targetHost).append(':').append(targetPort).append("\r\n");
        if (upUser != null && !upUser.isEmpty()) {
            String creds = Base64.encodeToString(
                (upUser + ":" + upPass).getBytes("UTF-8"), Base64.NO_WRAP);
            req.append("Proxy-Authorization: Basic ").append(creds).append("\r\n");
        }
        req.append("\r\n");
        out.write(req.toString().getBytes("ISO-8859-1"));
        out.flush();

        String status = readLine(in);
        while (!readLine(in).isEmpty()) {}   // drain headers
        if (!status.contains("200"))
            throw new IOException("HTTP proxy CONNECT refused: " + status);
        return sock;
    }

    /** SOCKS5 upstream proxy. */
    private Socket tunnelViaSocks5(String targetHost, int targetPort) throws IOException {
        Socket sock = new Socket(upHost, upPort);
        InputStream  in  = sock.getInputStream();
        OutputStream out = sock.getOutputStream();

        boolean hasAuth = (upUser != null && !upUser.isEmpty());

        // greeting
        out.write(hasAuth ? new byte[]{0x05, 0x02, 0x00, 0x02}
                          : new byte[]{0x05, 0x01, 0x00});
        out.flush();

        byte[] resp = readExactly(in, 2);
        if (resp[0] != 0x05) throw new IOException("Not a SOCKS5 proxy");
        int method = resp[1] & 0xFF;

        if (method == 0x02) {       // username/password auth
            byte[] u = upUser.getBytes("UTF-8");
            byte[] p = (upPass != null ? upPass : "").getBytes("UTF-8");
            byte[] authReq = new byte[3 + u.length + p.length];
            authReq[0] = 0x01;
            authReq[1] = (byte) u.length;
            System.arraycopy(u, 0, authReq, 2, u.length);
            authReq[2 + u.length] = (byte) p.length;
            System.arraycopy(p, 0, authReq, 3 + u.length, p.length);
            out.write(authReq); out.flush();
            byte[] authResp = readExactly(in, 2);
            if (authResp[1] != 0x00) throw new IOException("SOCKS5 auth failed");
        } else if (method == 0xFF) {
            throw new IOException("SOCKS5 proxy: no acceptable auth method");
        }

        // CONNECT request
        byte[] hostBytes = targetHost.getBytes("ISO-8859-1");
        byte[] connectReq = new byte[7 + hostBytes.length];
        connectReq[0] = 0x05; connectReq[1] = 0x01; connectReq[2] = 0x00;
        connectReq[3] = 0x03; // domain
        connectReq[4] = (byte) hostBytes.length;
        System.arraycopy(hostBytes, 0, connectReq, 5, hostBytes.length);
        connectReq[5 + hostBytes.length] = (byte)((targetPort >> 8) & 0xFF);
        connectReq[6 + hostBytes.length] = (byte)(targetPort & 0xFF);
        out.write(connectReq); out.flush();

        byte[] reply = readExactly(in, 4);
        if (reply[1] != 0x00)
            throw new IOException("SOCKS5 CONNECT failed, code=" + (reply[1] & 0xFF));
        // consume BND.ADDR and BND.PORT
        int atyp = reply[3] & 0xFF;
        if      (atyp == 0x01) readExactly(in, 4);
        else if (atyp == 0x03) readExactly(in, in.read());
        else if (atyp == 0x04) readExactly(in, 16);
        readExactly(in, 2); // port

        return sock;
    }

    // ── static helpers ────────────────────────────────────────────────

    static void relay(InputStream in, OutputStream out, Socket s1, Socket s2) {
        byte[] buf = new byte[65536];
        int n;
        try {
            while ((n = in.read(buf)) != -1) { out.write(buf, 0, n); out.flush(); }
        } catch (IOException ignored) {}
        finally {
            try { s1.shutdownOutput(); } catch (Exception ignored) {}
            try { s2.shutdownOutput(); } catch (Exception ignored) {}
        }
    }

    static byte[] readExactly(InputStream in, int count) throws IOException {
        byte[] buf = new byte[count];
        int read = 0;
        while (read < count) {
            int n = in.read(buf, read, count - read);
            if (n == -1) throw new IOException("Stream ended prematurely");
            read += n;
        }
        return buf;
    }

    static String readLine(InputStream in) throws IOException {
        StringBuilder sb = new StringBuilder();
        int c;
        while ((c = in.read()) != -1) {
            if (c == '\n') break;
            if (c != '\r') sb.append((char) c);
        }
        return sb.toString();
    }

    static void close(Socket s)       { if (s != null) try { s.close(); } catch (IOException ignored) {} }
    static void close(ServerSocket s) { if (s != null) try { s.close(); } catch (IOException ignored) {} }

    // ── notification ─────────────────────────────────────────────────

    private void broadcast(String msg) {
        Intent i = new Intent(BROADCAST_STATUS);
        i.putExtra(EXTRA_STATUS, msg);
        sendBroadcast(i);
    }

    private Notification buildNotification(String text) {
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(this, CHANNEL_ID);
        } else {
            //noinspection deprecation
            b = new Notification.Builder(this);
        }
        return b.setContentTitle("SuperPuperProxy")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                CHANNEL_ID, "SuperPuperProxy", NotificationManager.IMPORTANCE_LOW);
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE))
                .createNotificationChannel(ch);
        }
    }
}
