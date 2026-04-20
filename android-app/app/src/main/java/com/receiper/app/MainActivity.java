package com.receiper.app;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Toast;

import androidx.activity.result.ActivityResult;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import java.util.ArrayList;

public class MainActivity extends AppCompatActivity {
    private static final String PREFS = "receiper_prefs";
    private static final String KEY_URL = "server_url";
    private static final int CAMERA_PERMISSION_REQ = 5011;

    private WebView webView;
    private EditText urlEditText;
    private ValueCallbackCompat fileCallback;
    private PermissionRequest pendingPermissionRequest;

    private final ActivityResultLauncher<Intent> filePickerLauncher =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), this::onFilePickerResult);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        webView = findViewById(R.id.webView);
        urlEditText = findViewById(R.id.urlEditText);
        Button loadButton = findViewById(R.id.loadButton);
        Button reloadButton = findViewById(R.id.reloadButton);

        String savedUrl = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(KEY_URL, "https://your-receiper-api.onrender.com");
        urlEditText.setText(savedUrl);

        setupWebView();
        requestCameraPermissionIfNeeded();
        loadUrl(savedUrl);

        loadButton.setOnClickListener(v -> {
            String entered = normalizeUrl(urlEditText.getText().toString());
            if (entered.isEmpty()) {
                Toast.makeText(this, "Gecerli URL gir", Toast.LENGTH_SHORT).show();
                return;
            }

            getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .edit()
                    .putString(KEY_URL, entered)
                    .apply();
            loadUrl(entered);
        });

        reloadButton.setOnClickListener(v -> webView.reload());
    }

    private void setupWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(@NonNull WebView view, @NonNull WebResourceRequest request) {
                return false;
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> {
                    if (hasCameraPermission()) {
                        grantVideoPermission(request);
                    } else {
                        pendingPermissionRequest = request;
                        requestCameraPermissionIfNeeded();
                    }
                });
            }

            @Override
            public boolean onShowFileChooser(WebView webView,
                                             android.webkit.ValueCallback<Uri[]> filePathCallback,
                                             FileChooserParams fileChooserParams) {
                if (fileCallback != null) {
                    fileCallback.send(null);
                }
                fileCallback = new ValueCallbackCompat(filePathCallback);

                Intent intent;
                try {
                    intent = fileChooserParams.createIntent();
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "Dosya secici acilamadi", Toast.LENGTH_SHORT).show();
                    return false;
                }

                filePickerLauncher.launch(intent);
                return true;
            }
        });
    }

    private boolean hasCameraPermission() {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void requestCameraPermissionIfNeeded() {
        if (!hasCameraPermission()) {
            ActivityCompat.requestPermissions(
                    this,
                    new String[]{Manifest.permission.CAMERA},
                    CAMERA_PERMISSION_REQ
            );
        }
    }

    private void grantVideoPermission(PermissionRequest request) {
        ArrayList<String> granted = new ArrayList<>();
        for (String resource : request.getResources()) {
            if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)) {
                granted.add(resource);
            }
        }

        if (granted.isEmpty()) {
            request.deny();
            return;
        }

        request.grant(granted.toArray(new String[0]));
    }

    @Override
    public void onRequestPermissionsResult(int requestCode,
                                           @NonNull String[] permissions,
                                           @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);

        if (requestCode != CAMERA_PERMISSION_REQ) {
            return;
        }

        boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;

        if (pendingPermissionRequest != null) {
            if (granted) {
                grantVideoPermission(pendingPermissionRequest);
            } else {
                pendingPermissionRequest.deny();
            }
            pendingPermissionRequest = null;
        }

        if (!granted) {
            Toast.makeText(this, "Kamera izni olmadan otomatik cekim acilmaz", Toast.LENGTH_SHORT).show();
        }
    }

    private void onFilePickerResult(ActivityResult result) {
        if (fileCallback == null) {
            return;
        }

        Uri[] uris = WebChromeClient.FileChooserParams.parseResult(result.getResultCode(), result.getData());
        fileCallback.send(uris);
        fileCallback = null;
    }

    private void loadUrl(String url) {
        String normalized = normalizeUrl(url);
        if (normalized.isEmpty()) {
            return;
        }
        webView.loadUrl(normalized);
    }

    private String normalizeUrl(String url) {
        String trimmed = url == null ? "" : url.trim();
        if (trimmed.isEmpty()) {
            return "";
        }
        if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
            trimmed = "http://" + trimmed;
        }
        return trimmed;
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    private static class ValueCallbackCompat {
        private final android.webkit.ValueCallback<Uri[]> callback;

        ValueCallbackCompat(android.webkit.ValueCallback<Uri[]> callback) {
            this.callback = callback;
        }

        void send(Uri[] uris) {
            callback.onReceiveValue(uris);
        }
    }
}
