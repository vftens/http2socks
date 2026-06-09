package org.drvital.http2socks;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {

    private EditText etHost, etPort, etListenPort;
    private TextView tvStatus;

    private final BroadcastReceiver statusReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context ctx, Intent intent) {
            String msg = intent.getStringExtra(Socks5ProxyService.EXTRA_STATUS);
            runOnUiThread(() -> tvStatus.setText(msg));
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        etHost       = findViewById(R.id.et_host);
        etPort       = findViewById(R.id.et_port);
        etListenPort = findViewById(R.id.et_listen_port);
        tvStatus     = findViewById(R.id.tv_status);

        Button btnStart = findViewById(R.id.btn_start);
        Button btnStop  = findViewById(R.id.btn_stop);
        btnStart.setOnClickListener(v -> startProxy());
        btnStop .setOnClickListener(v -> stopProxy());
    }

    @Override
    protected void onResume() {
        super.onResume();
        registerReceiver(statusReceiver,
            new IntentFilter(Socks5ProxyService.BROADCAST_STATUS));
    }

    @Override
    protected void onPause() {
        super.onPause();
        unregisterReceiver(statusReceiver);
    }

    private void startProxy() {
        String host = etHost.getText().toString().trim();
        int port, listenPort;
        try {
            port       = Integer.parseInt(etPort.getText().toString().trim());
            listenPort = Integer.parseInt(etListenPort.getText().toString().trim());
        } catch (NumberFormatException e) {
            tvStatus.setText("❌ Invalid port number");
            return;
        }
        Intent intent = new Intent(this, Socks5ProxyService.class);
        intent.setAction(Socks5ProxyService.ACTION_START);
        intent.putExtra(Socks5ProxyService.EXTRA_PROXY_HOST,  host);
        intent.putExtra(Socks5ProxyService.EXTRA_PROXY_PORT,  port);
        intent.putExtra(Socks5ProxyService.EXTRA_LISTEN_PORT, listenPort);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        tvStatus.setText("Starting...");
    }

    private void stopProxy() {
        Intent intent = new Intent(this, Socks5ProxyService.class);
        intent.setAction(Socks5ProxyService.ACTION_STOP);
        startService(intent);
    }
}
