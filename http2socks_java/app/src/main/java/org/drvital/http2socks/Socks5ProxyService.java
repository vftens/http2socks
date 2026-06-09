package org.drvital.http2socks;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Foreground Service that runs the SOCKS5 → HTTP-proxy bridge.
 *
 * Listens for incoming SOCKS5 connections on LISTEN_PORT (default 1080),
 * performs the SOCKS5 handshake to learn the target host:port, then opens
 * a TCP connection to the configured upstream HTTP proxy and sends an
 * HTTP CONNECT request for that target. Once the proxy confirms with
 * "200 Connection established", it splices the two sockets together.
 */
public class Socks5ProxyService extends Service {

    static final String TAG            = "Socks5ProxySvc";
    static final String CHANNEL_ID     = "http2socks_channel";
    static final String ACTION_START   = "org.drvital.http2socks.START";
    static final String ACTION_STOP    = "org.drvital.http2socks.STOP";
    static final String EXTRA_PROXY_HOST   = "proxy_host";
    static final String EXTRA_PROXY_PORT   = "proxy_port";
    static final String EXTRA_LISTEN_PORT  = "listen_port";
    static final String BROADCAST_STATUS   = "org.drvital.http2socks.STATUS";
    static final String EXTRA_STATUS       = "status";

    private String proxyHost;
    private int    proxyPort;
    private int    listenPort;

    private ServerSocket  serverSocket;
    private ExecutorService executor;
    private volatile boolean running = false;

    // ── lifecycle ──────────────────────────────────────────────────────

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) return START_NOT_STICKY;
        String action = intent.getAction();
        if (ACTION_START.equals(action)) {
            proxyHost  = intent.getStringExtra(EXTRA_PROXY_HOST);
            proxyPort  = intent.getIntExtra(EXTRA_PROXY_PORT, 8888);
            listenPort = intent.getIntExtra(EXTRA_LISTEN_PORT, 1080);
            startForeground(1, buildNotification("Running on SOCKS5 port " + listenPort));
            startServer();
        } else if (ACTION_STOP.equals(action)) {
            stopServer();
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    // ── server ────────────────────────────────────────────────────────

    private void startServer() {
        executor = Executors.newCachedThreadPool();
        running  = true;
        executor.submit(() -> {
            try {
                serverSocket = new ServerSocket(listenPort);
                broadcast("✅ SOCKS5 listening on port " + listenPort +
                          "\nUpstream HTTP proxy: " + proxyHost + ":" + proxyPort +
                          "\n\nIn Telegram Mobile set proxy:\n  Type: SOCKS5\n  Server: <this device IP>\n  Port: " + listenPort);
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
        try { if (serverSocket != null) serverSocket.close(); } catch (IOException ignored) {}
        if (executor != null) executor.shutdownNow();
        broadcast("Stopped.");
    }

    // ── per-connection handler ────────────────────────────────────────

    private void handleClient(Socket client) {
        Socket upstream = null;
        try {
            InputStream  cin  = client.getInputStream();
            OutputStream cout = client.getOutputStream();

            // ── 1. SOCKS5 greeting ──────────────────────────────────
            int ver = cin.read();
            if (ver != 0x05) { Log.w(TAG, "Not SOCKS5"); return; }
            int nmethods = cin.read();
            //noinspection ResultOfMethodCallIgnored
            cin.read(new byte[nmethods]);           // discard method list
            cout.write(new byte[]{0x05, 0x00});     // choose NO AUTH
            cout.flush();

            // ── 2. SOCKS5 request ───────────────────────────────────
            byte[] req = readExactly(cin, 4);
            if (req[0] != 0x05 || req[1] != 0x01) { // only CONNECT
                cout.write(new byte[]{0x05, 0x07, 0x00, 0x01, 0,0,0,0, 0,0});
                cout.flush();
                return;
            }

            int    atyp = req[3] & 0xFF;
            String targetHost;
            if (atyp == 0x01) {                     // IPv4
                byte[] ip = readExactly(cin, 4);
                targetHost = (ip[0]&0xFF)+"."+( ip[1]&0xFF)+"."+( ip[2]&0xFF)+"."+( ip[3]&0xFF);
            } else if (atyp == 0x03) {              // domain name
                int len = cin.read();
                targetHost = new String(readExactly(cin, len));
            } else if (atyp == 0x04) {              // IPv6
                byte[] ip = readExactly(cin, 16);
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < 16; i += 2) {
                    if (i > 0) sb.append(':');
                    sb.append(String.format("%x", ((ip[i]&0xFF)<<8)|(ip[i+1]&0xFF)));
                }
                targetHost = sb.toString();
            } else {
                return;
            }
            byte[] portBytes = readExactly(cin, 2);
            int targetPort = ((portBytes[0]&0xFF) << 8) | (portBytes[1]&0xFF);

            // ── 3. Connect to upstream HTTP proxy ───────────────────
            upstream = new Socket(proxyHost, proxyPort);
            InputStream  uin  = upstream.getInputStream();
            OutputStream uout = upstream.getOutputStream();

            String connectReq =
                "CONNECT " + targetHost + ":" + targetPort + " HTTP/1.1\r\n" +
                "Host: "    + targetHost + ":" + targetPort + "\r\n\r\n";
            uout.write(connectReq.getBytes("ISO-8859-1"));
            uout.flush();

            // ── 4. Check 200 response ───────────────────────────────
            String statusLine = readLine(uin);
            while (!readLine(uin).isEmpty()) {}     // consume remaining headers
            if (!statusLine.contains("200")) {
                cout.write(new byte[]{0x05, 0x05, 0x00, 0x01, 0,0,0,0, 0,0}); // connection refused
                cout.flush();
                return;
            }

            // ── 5. SOCKS5 success reply ─────────────────────────────
            cout.write(new byte[]{0x05, 0x00, 0x00, 0x01, 0,0,0,0, 0,0});
            cout.flush();

            // ── 6. Bidirectional relay ──────────────────────────────
            final Socket up = upstream;
            Thread t1 = new Thread(() -> relay(cin,  uout, client, up));
            Thread t2 = new Thread(() -> relay(uin,  cout, up, client));
            t1.start(); t2.start();
            t1.join();  t2.join();

        } catch (Exception e) {
            Log.w(TAG, "Client error: " + e.getMessage());
        } finally {
            close(client);
            close(upstream);
        }
    }

    // ── static helpers ────────────────────────────────────────────────

    static void relay(InputStream in, OutputStream out, Socket s1, Socket s2) {
        byte[] buf = new byte[65536];
        int n;
        try {
            while ((n = in.read(buf)) != -1) {
                out.write(buf, 0, n);
                out.flush();
            }
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

    static void close(Socket s) {
        if (s != null) try { s.close(); } catch (IOException ignored) {}
    }

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
        return b.setContentTitle("http2socks")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                CHANNEL_ID, "http2socks proxy", NotificationManager.IMPORTANCE_LOW);
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE))
                .createNotificationChannel(ch);
        }
    }
}
