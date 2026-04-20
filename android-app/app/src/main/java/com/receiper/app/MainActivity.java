package com.receiper.app;

import android.Manifest;
import android.animation.ObjectAnimator;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Matrix;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends AppCompatActivity {
    private static final String PREFS = "receiper_prefs";
    private static final String KEY_TOKEN = "access_token";
    private static final String BASE_URL = "https://receiper.onrender.com";
    private static final String HEALTH_PATH = "/health";
    private static final String AUTH_LOGIN_PATH = "/api/auth/login";
    private static final String AUTH_ME_PATH = "/api/auth/me";
    private static final String MOBILE_UPLOAD_PATH = "/api/mobile/receipts";
    private static final int CAMERA_PERMISSION_REQ = 5011;
    private static final int MAX_CONNECT_ATTEMPTS = 3;
    private static final int MAX_UPLOAD_ATTEMPTS = 3;
    private static final int TARGET_UPLOAD_EDGE = 1800;
    private static final int INITIAL_JPEG_QUALITY = 88;
    private static final long MAX_UPLOAD_IMAGE_BYTES = 1_700_000L;
    private static final int UPLOAD_CONNECT_TIMEOUT_MS = 30_000;
    private static final int UPLOAD_READ_TIMEOUT_MS = 180_000;

    private LinearLayout loadingScreen;
    private LinearLayout loginScreen;
    private LinearLayout scanScreen;
    private TextView loadingMessage;
    private TextView loadingPulse;
    private Button retryConnectButton;
    private EditText emailInput;
    private EditText passwordInput;
    private Button loginButton;
    private TextView loginStatus;
    private Button scanButton;
    private TextView scanStatus;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private ObjectAnimator loadingAnimator;

    private int connectAttempt = 0;
    private boolean scanBusy = false;
    private File currentPhotoFile;

    private final ActivityResultLauncher<Uri> takePictureLauncher =
            registerForActivityResult(new ActivityResultContracts.TakePicture(), this::onTakePictureResult);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        loadingScreen = findViewById(R.id.loadingScreen);
        loginScreen = findViewById(R.id.loginScreen);
        scanScreen = findViewById(R.id.scanScreen);
        loadingMessage = findViewById(R.id.loadingMessage);
        loadingPulse = findViewById(R.id.loadingPulse);
        retryConnectButton = findViewById(R.id.retryConnectButton);
        emailInput = findViewById(R.id.emailInput);
        passwordInput = findViewById(R.id.passwordInput);
        loginButton = findViewById(R.id.loginButton);
        loginStatus = findViewById(R.id.loginStatus);
        scanButton = findViewById(R.id.scanButton);
        scanStatus = findViewById(R.id.scanStatus);

        retryConnectButton.setOnClickListener(v -> startBootstrapFlow());
        loginButton.setOnClickListener(v -> attemptLogin());
        scanButton.setOnClickListener(v -> beginScanAndUpload());

        startLoadingAnimation();
        startBootstrapFlow();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (loadingAnimator != null) {
            loadingAnimator.cancel();
        }
        executor.shutdownNow();
    }

    private void startLoadingAnimation() {
        loadingAnimator = ObjectAnimator.ofFloat(loadingPulse, "alpha", 0.35f, 1f);
        loadingAnimator.setDuration(950L);
        loadingAnimator.setRepeatCount(ObjectAnimator.INFINITE);
        loadingAnimator.setRepeatMode(ObjectAnimator.REVERSE);
        loadingAnimator.start();
    }

    private void startBootstrapFlow() {
        connectAttempt = 0;
        showLoadingScreen();
        retryConnectButton.setVisibility(View.GONE);
        loadingMessage.setText("Uygulama yükleniyor, lütfen bekleyin");
        loadingPulse.setText("Yükleniyor...");
        runHealthAttempt();
    }

    private void runHealthAttempt() {
        connectAttempt += 1;
        loadingPulse.setText("Yükleniyor... (" + connectAttempt + "/" + MAX_CONNECT_ATTEMPTS + ")");

        executor.execute(() -> {
            HttpResult result = httpGet(HEALTH_PATH, null, 12000, 20000);
            boolean ok = result.code >= 200 && result.code < 300;

            mainHandler.post(() -> {
                if (ok) {
                    validateSavedSessionOrShowLogin();
                    return;
                }

                if (connectAttempt < MAX_CONNECT_ATTEMPTS) {
                    loadingMessage.setText("Sunucu başlatılıyor olabilir, tekrar deneniyor...");
                    mainHandler.postDelayed(this::runHealthAttempt, 1600);
                    return;
                }

                loadingMessage.setText("Bağlanılamadı. Sunucu cevap vermedi.");
                loadingPulse.setText("Lütfen tekrar dene.");
                retryConnectButton.setVisibility(View.VISIBLE);
            });
        });
    }

    private void validateSavedSessionOrShowLogin() {
        String token = getStoredToken();
        if (token.isEmpty()) {
            showLoginScreen();
            return;
        }

        executor.execute(() -> {
            HttpResult result = httpGet(AUTH_ME_PATH, token, 10000, 20000);
            mainHandler.post(() -> {
                if (result.code >= 200 && result.code < 300) {
                    showScanScreen();
                    setScanStatus("Hazır.", false);
                } else {
                    clearStoredToken();
                    showLoginScreen();
                }
            });
        });
    }

    private void attemptLogin() {
        String email = emailInput.getText().toString().trim();
        String password = passwordInput.getText().toString();

        if (email.isEmpty() || password.isEmpty()) {
            setLoginStatus("E-posta ve şifre zorunlu.", true);
            return;
        }

        loginButton.setEnabled(false);
        setLoginStatus("Giriş yapılıyor...", false);

        executor.execute(() -> {
            String body = "{\"email\":\"" + escapeJson(email) + "\",\"password\":\"" + escapeJson(password) + "\"}";
            HttpResult result = httpPostJson(AUTH_LOGIN_PATH, null, body);

            mainHandler.post(() -> {
                loginButton.setEnabled(true);

                if (result.code >= 200 && result.code < 300) {
                    try {
                        JSONObject obj = new JSONObject(result.body);
                        String token = obj.optString("access_token", "");
                        if (token.isEmpty()) {
                            setLoginStatus("Token alınamadı.", true);
                            return;
                        }
                        saveToken(token);
                        setLoginStatus("", false);
                        showScanScreen();
                        setScanStatus("Hazır.", false);
                    } catch (Exception parseError) {
                        setLoginStatus("Giriş yanıtı okunamadı.", true);
                    }
                    return;
                }

                setLoginStatus(extractErrorMessage(result.body, "Giriş başarısız."), true);
            });
        });
    }

    private void beginScanAndUpload() {
        if (scanBusy) {
            return;
        }
        if (!hasCameraPermission()) {
            requestCameraPermission();
            return;
        }

        Uri imageUri = createCaptureUri();
        if (imageUri == null) {
            setScanStatus("Kamera dosyası oluşturulamadı.", true);
            return;
        }

        setScanBusy(true);
        setScanStatus("Kamera açılıyor...", false);
        takePictureLauncher.launch(imageUri);
    }

    private void onTakePictureResult(Boolean success) {
        if (Boolean.TRUE.equals(success)) {
            uploadCurrentPhoto();
            return;
        }
        setScanBusy(false);
        setScanStatus("Çekim iptal edildi.", true);
    }

    private void uploadCurrentPhoto() {
        if (currentPhotoFile == null || !currentPhotoFile.exists()) {
            setScanBusy(false);
            setScanStatus("Fotoğraf bulunamadı.", true);
            return;
        }

        String token = getStoredToken();
        if (token.isEmpty()) {
            setScanBusy(false);
            showLoginScreen();
            return;
        }

        setScanStatus("Fiş hazırlanıyor...", false);
        executor.execute(() -> {
            File uploadFile = currentPhotoFile;
            boolean deleteAfterUpload = false;
            try {
                File optimized = optimizePhotoForUpload(currentPhotoFile);
                if (optimized != null && optimized.exists()) {
                    uploadFile = optimized;
                    deleteAfterUpload = !optimized.equals(currentPhotoFile);
                }
            } catch (Exception ignore) {
                uploadFile = currentPhotoFile;
                deleteAfterUpload = false;
            }

            HttpResult result = new HttpResult(-1, "");
            for (int attempt = 1; attempt <= MAX_UPLOAD_ATTEMPTS; attempt++) {
                int currentAttempt = attempt;
                mainHandler.post(() -> setScanStatus(
                        "Fiş gönderiliyor... (" + currentAttempt + "/" + MAX_UPLOAD_ATTEMPTS + ")",
                        false
                ));
                result = httpPostMultipartImage(
                        MOBILE_UPLOAD_PATH,
                        token,
                        uploadFile,
                        UPLOAD_CONNECT_TIMEOUT_MS,
                        UPLOAD_READ_TIMEOUT_MS
                );
                if (!shouldRetryUpload(result, attempt)) {
                    break;
                }
                try {
                    Thread.sleep(1300L * attempt);
                } catch (InterruptedException interruptedException) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }

            if (deleteAfterUpload) {
                uploadFile.delete();
            }

            HttpResult finalResult = result;
            mainHandler.post(() -> {
                setScanBusy(false);

                if (finalResult.code >= 200 && finalResult.code < 300) {
                    setScanStatus(buildUploadSuccessMessage(finalResult.body), false);
                    return;
                }

                if (finalResult.code == 401) {
                    clearStoredToken();
                    showLoginScreen();
                    setLoginStatus("Oturum süresi doldu, tekrar giriş yap.", true);
                    return;
                }

                setScanStatus(extractErrorMessage(finalResult.body, "Gönderim başarısız."), true);
            });
        });
    }

    private boolean shouldRetryUpload(HttpResult result, int attempt) {
        if (attempt >= MAX_UPLOAD_ATTEMPTS) {
            return false;
        }

        if (result.code == 401) {
            return false;
        }

        if (result.code >= 400 && result.code < 500 && result.code != 429) {
            return false;
        }

        return true;
    }

    private String buildUploadSuccessMessage(String body) {
        try {
            JSONObject obj = new JSONObject(body);
            boolean aiUsed = obj.optBoolean("ai_used", false);
            double confidence = obj.optDouble("parse_confidence", -1);
            if (confidence < 0) {
                return "İşlendi, sıradaki fiş.";
            }
            int percent = (int) Math.round(confidence * 100);
            if (aiUsed) {
                return "İşlendi, sıradaki fiş. (AI doğrulama: %" + percent + ")";
            }
            return "İşlendi, sıradaki fiş. (Doğruluk: %" + percent + ")";
        } catch (Exception ignore) {
            return "İşlendi, sıradaki fiş.";
        }
    }

    private File optimizePhotoForUpload(File sourceFile) throws IOException {
        Bitmap bitmap = decodeScaledBitmap(sourceFile, TARGET_UPLOAD_EDGE);
        if (bitmap == null) {
            return sourceFile;
        }

        Bitmap rotated = applyExifRotation(sourceFile, bitmap);
        if (rotated == null) {
            bitmap.recycle();
            return sourceFile;
        }

        byte[] compressed = null;
        int quality = INITIAL_JPEG_QUALITY;
        while (quality >= 66) {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            rotated.compress(Bitmap.CompressFormat.JPEG, quality, bos);
            byte[] bytes = bos.toByteArray();
            if (bytes.length <= MAX_UPLOAD_IMAGE_BYTES || quality <= 66) {
                compressed = bytes;
                break;
            }
            quality -= 6;
        }

        if (compressed == null || compressed.length == 0) {
            rotated.recycle();
            return sourceFile;
        }

        File optimized = new File(sourceFile.getParentFile(), "upload_" + sourceFile.getName());
        try (FileOutputStream fos = new FileOutputStream(optimized)) {
            fos.write(compressed);
        }

        rotated.recycle();
        return optimized;
    }

    private Bitmap decodeScaledBitmap(File sourceFile, int targetEdge) {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(sourceFile.getAbsolutePath(), bounds);

        int width = bounds.outWidth;
        int height = bounds.outHeight;
        if (width <= 0 || height <= 0) {
            return null;
        }

        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = calculateInSampleSize(width, height, targetEdge);
        options.inPreferredConfig = Bitmap.Config.ARGB_8888;
        return BitmapFactory.decodeFile(sourceFile.getAbsolutePath(), options);
    }

    private int calculateInSampleSize(int width, int height, int targetEdge) {
        int sampleSize = 1;
        int largest = Math.max(width, height);
        while ((largest / sampleSize) > targetEdge) {
            sampleSize *= 2;
        }
        return Math.max(1, sampleSize);
    }

    private Bitmap applyExifRotation(File sourceFile, Bitmap bitmap) {
        try {
            ExifInterface exif = new ExifInterface(sourceFile.getAbsolutePath());
            int orientation = exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL);

            Matrix matrix = new Matrix();
            if (orientation == ExifInterface.ORIENTATION_ROTATE_90) {
                matrix.postRotate(90f);
            } else if (orientation == ExifInterface.ORIENTATION_ROTATE_180) {
                matrix.postRotate(180f);
            } else if (orientation == ExifInterface.ORIENTATION_ROTATE_270) {
                matrix.postRotate(270f);
            } else {
                return bitmap;
            }

            Bitmap rotated = Bitmap.createBitmap(bitmap, 0, 0, bitmap.getWidth(), bitmap.getHeight(), matrix, true);
            if (rotated != bitmap) {
                bitmap.recycle();
            }
            return rotated;
        } catch (IOException e) {
            return bitmap;
        }
    }

    private Uri createCaptureUri() {
        try {
            File dir = new File(getCacheDir(), "captures");
            if (!dir.exists() && !dir.mkdirs()) {
                return null;
            }
            currentPhotoFile = new File(dir, "receipt_" + System.currentTimeMillis() + ".jpg");
            return FileProvider.getUriForFile(
                    this,
                    getPackageName() + ".fileprovider",
                    currentPhotoFile
            );
        } catch (Exception e) {
            return null;
        }
    }

    private HttpResult httpGet(String path, String token, int connectTimeoutMs, int readTimeoutMs) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(BASE_URL + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(connectTimeoutMs);
            conn.setReadTimeout(readTimeoutMs);
            conn.setRequestProperty("Accept", "application/json");
            if (token != null && !token.isEmpty()) {
                conn.setRequestProperty("Authorization", "Bearer " + token);
            }

            int code = conn.getResponseCode();
            String body = readResponseBody(conn);
            return new HttpResult(code, body);
        } catch (Exception ex) {
            return new HttpResult(-1, ex.getMessage() == null ? "Network error" : ex.getMessage());
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private HttpResult httpPostJson(String path, String token, String body) {
        HttpURLConnection conn = null;
        try {
            byte[] data = body.getBytes(StandardCharsets.UTF_8);
            URL url = new URL(BASE_URL + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(12000);
            conn.setReadTimeout(24000);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
            conn.setRequestProperty("Accept", "application/json");
            if (token != null && !token.isEmpty()) {
                conn.setRequestProperty("Authorization", "Bearer " + token);
            }

            conn.getOutputStream().write(data);
            int code = conn.getResponseCode();
            String responseBody = readResponseBody(conn);
            return new HttpResult(code, responseBody);
        } catch (Exception ex) {
            return new HttpResult(-1, ex.getMessage() == null ? "Network error" : ex.getMessage());
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private HttpResult httpPostMultipartImage(
            String path,
            String token,
            File imageFile,
            int connectTimeoutMs,
            int readTimeoutMs
    ) {
        HttpURLConnection conn = null;
        String boundary = "----ReceiperBoundary" + System.currentTimeMillis();
        try {
            URL url = new URL(BASE_URL + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(connectTimeoutMs);
            conn.setReadTimeout(readTimeoutMs);
            conn.setDoOutput(true);
            conn.setRequestProperty("Authorization", "Bearer " + token);
            conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            conn.setRequestProperty("Accept", "application/json");

            try (DataOutputStream out = new DataOutputStream(conn.getOutputStream());
                 FileInputStream fileIn = new FileInputStream(imageFile)) {
                out.writeBytes("--" + boundary + "\r\n");
                out.writeBytes("Content-Disposition: form-data; name=\"file\"; filename=\"" + imageFile.getName() + "\"\r\n");
                out.writeBytes("Content-Type: image/jpeg\r\n\r\n");

                byte[] buffer = new byte[8192];
                int read;
                while ((read = fileIn.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                }
                out.writeBytes("\r\n--" + boundary + "--\r\n");
                out.flush();
            }

            int code = conn.getResponseCode();
            String responseBody = readResponseBody(conn);
            return new HttpResult(code, responseBody);
        } catch (Exception ex) {
            return new HttpResult(-1, ex.getMessage() == null ? "Network error" : ex.getMessage());
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private String readResponseBody(HttpURLConnection conn) throws IOException {
        InputStream stream = conn.getResponseCode() >= 400 ? conn.getErrorStream() : conn.getInputStream();
        if (stream == null) {
            return "";
        }
        try (BufferedInputStream bis = new BufferedInputStream(stream);
             BufferedReader reader = new BufferedReader(new InputStreamReader(bis, StandardCharsets.UTF_8))) {
            StringBuilder builder = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
            return builder.toString();
        }
    }

    private String extractErrorMessage(String body, String fallback) {
        try {
            JSONObject obj = new JSONObject(body);
            String detail = obj.optString("detail", "").trim();
            if (!detail.isEmpty()) {
                return detail;
            }
            String message = obj.optString("message", "").trim();
            if (!message.isEmpty()) {
                return message;
            }
            return fallback;
        } catch (Exception ignore) {
            return fallback;
        }
    }

    private String escapeJson(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private boolean hasCameraPermission() {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void requestCameraPermission() {
        ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION_REQ);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != CAMERA_PERMISSION_REQ) {
            return;
        }

        boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        if (granted) {
            beginScanAndUpload();
        } else {
            setScanStatus("Kamera izni gerekli.", true);
        }
    }

    private void showLoadingScreen() {
        loadingScreen.setVisibility(View.VISIBLE);
        loginScreen.setVisibility(View.GONE);
        scanScreen.setVisibility(View.GONE);
    }

    private void showLoginScreen() {
        loadingScreen.setVisibility(View.GONE);
        loginScreen.setVisibility(View.VISIBLE);
        scanScreen.setVisibility(View.GONE);
    }

    private void showScanScreen() {
        loadingScreen.setVisibility(View.GONE);
        loginScreen.setVisibility(View.GONE);
        scanScreen.setVisibility(View.VISIBLE);
    }

    private void setLoginStatus(String text, boolean isError) {
        loginStatus.setText(text);
        loginStatus.setTextColor(isError ? Color.parseColor("#FF8B8B") : Color.WHITE);
    }

    private void setScanStatus(String text, boolean isError) {
        scanStatus.setText(text);
        scanStatus.setTextColor(isError ? Color.parseColor("#FF8B8B") : Color.WHITE);
    }

    private void setScanBusy(boolean busy) {
        scanBusy = busy;
        scanButton.setEnabled(!busy);
    }

    private void saveToken(String token) {
        getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_TOKEN, token).apply();
    }

    private void clearStoredToken() {
        getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY_TOKEN).apply();
    }

    private String getStoredToken() {
        String token = getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_TOKEN, "");
        return token == null ? "" : token.trim();
    }

    private static final class HttpResult {
        final int code;
        final String body;

        HttpResult(int code, String body) {
            this.code = code;
            this.body = body == null ? "" : body;
        }
    }
}
