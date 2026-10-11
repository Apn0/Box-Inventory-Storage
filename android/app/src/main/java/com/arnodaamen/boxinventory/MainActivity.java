package com.arnodaamen.boxinventory;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * A WebView around the Box Inventory app, bundled in the APK.
 *
 * The page talks to the Google Sheet directly (CSV export to read, a Form to
 * write), so it works anywhere with internet and needs no server. The PC's
 * server.py is optional and only for photo identification; its address is
 * configurable from the menu.
 *
 * What the shell adds over a browser tab: file-chooser plumbing (a WebView does
 * not handle <input type="file"> at all without onShowFileChooser) and the
 * on-device speech bridge (a WebView has no Web Speech API).
 */
public class MainActivity extends Activity {

    private static final String PREFS = "boxinventory";
    private static final String KEY_URL = "server_url";
    private static final String DEFAULT_URL = "http://192.168.1.140:8781";
    private static final String APP_URL = "file:///android_asset/index.html";
    private static final int REQ_FILE = 1001;

    private WebView web;
    private ValueCallback<Uri[]> pendingCallback;
    private Uri pendingCameraUri;
    private SpeechBridge speech;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        // The app keeps local edits in localStorage — without this they vanish
        // every time the activity is recreated.
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        // The app ships inside the APK and talks to Google Sheets itself, so the
        // asset page needs cross-origin XHR. Universal access is scoped to
        // file:// pages, and the only file:// page this WebView ever loads is
        // our own asset — it is not a general browser.
        s.setAllowFileAccess(false);      // assets stay readable regardless
        s.setAllowContentAccess(false);
        s.setAllowUniversalAccessFromFileURLs(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                return false;   // keep every navigation inside the app
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                // The app ships in the APK; only a broken build fails here.
                if (req.isForMainFrame()) showUnreachable();
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                // Tell the page where the photo server lives (menu-configurable).
                // The page's own default matches, so a first launch works too.
                v.evaluateJavascript(
                    "window.BOXINV_SERVER=" + JSONObject.quote(serverUrl()) + ";"
                    + "try{localStorage.setItem('boxinv.server',window.BOXINV_SERVER)}catch(e){}",
                    null);
            }
        });

        // Speech for the page. Safe to expose because this WebView only ever
        // loads the one address you configure — it is not a general browser.
        speech = new SpeechBridge(this, web);
        web.addJavascriptInterface(speech, "AndroidSpeech");

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (pendingCallback != null) pendingCallback.onReceiveValue(null);
                pendingCallback = callback;
                return openPicker(params);
            }
        });

        // The app is bundled: it starts instantly, works anywhere with internet
        // (Google Sheet directly), and probes the PC only for photo features.
        web.loadUrl(APP_URL);
    }

    // ------------------------------------------------------------- settings
    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private String serverUrl() {
        return prefs().getString(KEY_URL, DEFAULT_URL);
    }

    private void askForUrl() {
        final EditText field = new EditText(this);
        field.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        field.setText(serverUrl());
        field.setSelectAllOnFocus(true);

        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(pad, pad, pad, 0);
        box.addView(field);

        new AlertDialog.Builder(this)
                .setTitle("Photo server address")
                .setMessage("Only photo identification needs the PC.\n"
                        + "Counts and search talk to the Google Sheet directly.\n"
                        + "At home: the PC's LAN address. Away: its Meshnet address.")
                .setView(box)
                .setPositiveButton("Save", (d, w) -> {
                    String url = field.getText().toString().trim();
                    if (url.isEmpty()) return;
                    if (!url.startsWith("http://") && !url.startsWith("https://")) {
                        url = "http://" + url;
                    }
                    prefs().edit().putString(KEY_URL, url).apply();
                    web.loadUrl(APP_URL);   // reload so the page re-probes it
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void showUnreachable() {
        TextView t = new TextView(this);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        t.setPadding(pad, pad * 3, pad, pad);
        t.setTextColor(Color.parseColor("#E8ECF3"));
        t.setTextSize(15f);
        t.setText("The app page failed to load from the APK.\n\n"
                + "That should not happen — reinstall the latest build.\n"
                + "Menu → Reload to try again.");

        LinearLayout wrap = new LinearLayout(this);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.setBackgroundColor(Color.parseColor("#0E1117"));
        wrap.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        wrap.addView(t);
        setContentView(wrap);
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "Reload");
        menu.add(0, 2, 1, "Photo server address");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == 1) {
            setContentView(web);
            web.loadUrl(APP_URL);
            return true;
        }
        if (item.getItemId() == 2) {
            askForUrl();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    // -------------------------------------------------------- file chooser
    /** Honours the page's `capture` attribute: camera on tap, gallery on long-press. */
    private boolean openPicker(WebChromeClient.FileChooserParams params) {
        boolean wantsCamera = params.isCaptureEnabled();
        boolean multiple = params.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE;

        Intent gallery = new Intent(Intent.ACTION_GET_CONTENT);
        gallery.setType("image/*");
        gallery.addCategory(Intent.CATEGORY_OPENABLE);
        gallery.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);

        Intent camera = null;
        if (wantsCamera) {
            // A MediaStore destination avoids needing a FileProvider *and* keeps
            // the full-resolution image — the thumbnail an EXTRA_OUTPUT-less
            // capture returns is useless for identifying a part.
            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.DISPLAY_NAME,
                    "boxinv_" + System.currentTimeMillis() + ".jpg");
            values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
            pendingCameraUri = getContentResolver().insert(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
            if (pendingCameraUri != null) {
                camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                camera.putExtra(MediaStore.EXTRA_OUTPUT, pendingCameraUri);
                camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                if (camera.resolveActivity(getPackageManager()) == null) {
                    camera = null;   // no camera app installed
                }
            }
        }

        // When the page asked for the camera, open the camera — do not wrap it in
        // a chooser. A chooser puts a dialog in front of every single photo and
        // offers the gallery as an equal option, which is what made the camera
        // button feel like a gallery button.
        Intent launch;
        if (camera != null) {
            launch = camera;
        } else if (wantsCamera) {
            // Asked for the camera but there is none available.
            finishChooser(null);
            Toast.makeText(this, "No camera app found", Toast.LENGTH_LONG).show();
            return false;
        } else {
            launch = Intent.createChooser(gallery, "Pick photos");
        }

        try {
            startActivityForResult(launch, REQ_FILE);
            return true;
        } catch (Exception e) {
            if (pendingCameraUri != null) {
                getContentResolver().delete(pendingCameraUri, null, null);
            }
            finishChooser(null);
            Toast.makeText(this, "Could not open the camera", Toast.LENGTH_LONG).show();
            return false;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode != REQ_FILE) {
            super.onActivityResult(requestCode, resultCode, data);
            return;
        }
        if (resultCode != RESULT_OK) {
            // The user backed out — drop the placeholder row the camera intent made.
            if (pendingCameraUri != null) {
                getContentResolver().delete(pendingCameraUri, null, null);
            }
            finishChooser(null);
            return;
        }

        Uri[] result = null;
        if (data != null && data.getClipData() != null) {          // several from gallery
            android.content.ClipData clip = data.getClipData();
            result = new Uri[clip.getItemCount()];
            for (int i = 0; i < clip.getItemCount(); i++) {
                result[i] = clip.getItemAt(i).getUri();
            }
        } else if (data != null && data.getData() != null) {       // one from gallery
            result = new Uri[]{data.getData()};
        } else if (pendingCameraUri != null) {                     // camera wrote to our URI
            result = new Uri[]{pendingCameraUri};
        }

        finishChooser(result);
    }

    private void finishChooser(Uri[] uris) {
        if (pendingCallback != null) {
            pendingCallback.onReceiveValue(uris);
            pendingCallback = null;
        }
        pendingCameraUri = null;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        if (requestCode == SpeechBridge.requestCode()) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            speech.onPermissionResult(granted);
            return;
        }
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
    }

    @Override
    protected void onDestroy() {
        if (speech != null) speech.release();
        super.onDestroy();
    }

    @Override
    protected void onPause() {
        // Do not hold the microphone while the app is in the background.
        if (speech != null) speech.stop();
        super.onPause();
    }

    // --------------------------------------------------------------- back
    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
