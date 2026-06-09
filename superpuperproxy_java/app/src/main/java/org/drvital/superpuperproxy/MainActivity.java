package org.drvital.superpuperproxy;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Spinner;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {

    private Spinner  spType;
    private EditText etHost, etPort, etUser, etPass, etListenPort;
    private TextView tvStatus;

    private final BroadcastReceiver statusReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context ctx, Intent intent) {
            String msg = intent.getStringExtra(SuperProxyService.EXTRA_STATUS);
            runOnUiThread(() -> tvStatus.setText(msg));
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        spType      = findViewById(R.id.sp_type);
        etHost      = findViewById(R.id.et_host);
        etPort      = findViewById(R.id.et_port);
        etUser      = findViewById(R.id.et_user);
        etPass      = findViewById(R.id.et_pass);
        etListenPort = findViewById(R.id.et_listen_port);
        tvStatus    = findViewById(R.id.tv_status);

        // Populate proxy-type spinner
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
            android.R.layout.simple_spinner_item,
            new String[]{"socks5", "http", "https"});
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spType.setAdapter(adapter);

        // Update default port hint when type changes
        spType.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                String type = (String) spType.getItemAtPosition(pos);
                if (etPort.getText().toString().trim().isEmpty()) {
                    etPort.setHint("http".equals(type) || "https".equals(type) ? "8080" : "1080");
                }
            }
            @Override public void onNothingSelected(AdapterView<?> p) {}
        });

        Button btnStart = findViewById(R.id.btn_start);
        Button btnStop  = findViewById(R.id.btn_stop);
        btnStart.setOnClickListener(v -> startProxy());
        btnStop .setOnClickListener(v -> stopProxy());
    }

    @Override protected void onResume() {
        super.onResume();
        registerReceiver(statusReceiver,
            new IntentFilter(SuperProxyService.BROADCAST_STATUS));
    }

    @Override protected void onPause() {
        super.onPause();
        unregisterReceiver(statusReceiver);
    }

    private void startProxy() {
        String type = (String) spType.getSelectedItem();
        String host = etHost.getText().toString().trim();
        String user = etUser.getText().toString().trim();
        String pass = etPass.getText().toString().trim();
        int port, listenPort;
        try {
            port       = Integer.parseInt(etPort.getText().toString().trim());
            listenPort = Integer.parseInt(etListenPort.getText().toString().trim());
        } catch (NumberFormatException e) {
            tvStatus.setText("❌ Invalid port number");
            return;
        }
        Intent intent = new Intent(this, SuperProxyService.class);
        intent.setAction(SuperProxyService.ACTION_START);
        intent.putExtra(SuperProxyService.EXTRA_UP_TYPE,    type);
        intent.putExtra(SuperProxyService.EXTRA_UP_HOST,    host);
        intent.putExtra(SuperProxyService.EXTRA_UP_PORT,    port);
        intent.putExtra(SuperProxyService.EXTRA_UP_USER,    user);
        intent.putExtra(SuperProxyService.EXTRA_UP_PASS,    pass);
        intent.putExtra(SuperProxyService.EXTRA_LISTEN_PORT, listenPort);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        tvStatus.setText("Starting...");
    }

    private void stopProxy() {
        Intent intent = new Intent(this, SuperProxyService.class);
        intent.setAction(SuperProxyService.ACTION_STOP);
        startService(intent);
    }
}
