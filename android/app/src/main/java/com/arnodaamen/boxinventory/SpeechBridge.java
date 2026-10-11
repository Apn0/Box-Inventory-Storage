package com.arnodaamen.boxinventory;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Locale;

/**
 * On-device speech for the page, exposed to JavaScript as `window.AndroidSpeech`.
 *
 * A WebView does not implement the Web Speech API at all — `webkitSpeechRecognition`
 * is simply undefined — so the page cannot listen on its own inside the app. This
 * bridges Android's own recogniser instead, which has two advantages beyond merely
 * working: it runs on the device (no per-minute API cost) and the restart policy is
 * ours, so the channel stays open while you walk to a container rather than closing
 * after a few seconds of silence.
 */
public class SpeechBridge {

    private static final int REQ_MIC = 2001;
    /** en-US throughout, matching the rest of the app. */
    private static final Locale LOCALE = Locale.US;

    private final Activity activity;
    private final WebView web;

    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private boolean ttsReady;
    private boolean keepListening;
    /** Set while the mic is deliberately paused so our own speech is not heard. */
    private boolean muted;

    SpeechBridge(Activity activity, WebView web) {
        this.activity = activity;
        this.web = web;
        this.tts = new TextToSpeech(activity, status -> {
            ttsReady = status == TextToSpeech.SUCCESS;
            if (ttsReady) tts.setLanguage(LOCALE);
        });
    }

    // ------------------------------------------------------------ JS surface
    @JavascriptInterface
    public boolean available() {
        return SpeechRecognizer.isRecognitionAvailable(activity);
    }

    @JavascriptInterface
    public void start(final boolean continuous) {
        activity.runOnUiThread(() -> {
            keepListening = continuous;
            if (!hasMic()) {
                activity.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                return;                       // JS is told once the grant lands
            }
            beginListening();
        });
    }

    @JavascriptInterface
    public void stop() {
        activity.runOnUiThread(() -> {
            keepListening = false;
            destroyRecognizer();
        });
    }

    /** Speak, with the microphone held off so the recogniser does not hear us. */
    @JavascriptInterface
    public void speak(final String text) {
        activity.runOnUiThread(() -> {
            if (!ttsReady || text == null || text.isEmpty()) {
                toJs("window.onSpeechSpoken && window.onSpeechSpoken()");
                return;
            }
            muted = true;
            destroyRecognizer();
            tts.setOnUtteranceProgressListener(new android.speech.tts.UtteranceProgressListener() {
                @Override public void onStart(String id) { }
                @Override public void onDone(String id) { resumeAfterSpeaking(); }
                @Override public void onError(String id) { resumeAfterSpeaking(); }
            });
            Bundle params = new Bundle();
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, params, "boxinv");
        });
    }

    @JavascriptInterface
    public boolean isListening() {
        return recognizer != null;
    }

    // ------------------------------------------------------------- internals
    private boolean hasMic() {
        return activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED;
    }

    /** Called by MainActivity when the permission dialog is answered. */
    void onPermissionResult(boolean granted) {
        if (granted) beginListening();
        else toJs("window.onSpeechError && window.onSpeechError('not-allowed')");
    }

    private void resumeAfterSpeaking() {
        activity.runOnUiThread(() -> {
            muted = false;
            toJs("window.onSpeechSpoken && window.onSpeechSpoken()");
            if (keepListening) beginListening();
        });
    }

    private void beginListening() {
        if (muted) return;
        destroyRecognizer();
        if (!SpeechRecognizer.isRecognitionAvailable(activity)) {
            toJs("window.onSpeechError && window.onSpeechError('unavailable')");
            return;
        }

        // Prefer the on-device recogniser where the platform offers one: no audio
        // leaves the phone and there is no network round trip between answers.
        if (Build.VERSION.SDK_INT >= 33
                && SpeechRecognizer.isOnDeviceRecognitionAvailable(activity)) {
            recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(activity);
        } else {
            recognizer = SpeechRecognizer.createSpeechRecognizer(activity);
        }

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, LOCALE.toLanguageTag());
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true);
        // Long silences are expected — you are walking to a shelf, not pausing.
        intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 4000L);
        intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 4000L);
        intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 1500L);

        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle p) {
                toJs("window.onSpeechState && window.onSpeechState('ready')");
            }
            @Override public void onBeginningOfSpeech() {
                toJs("window.onSpeechState && window.onSpeechState('hearing')");
            }
            @Override public void onRmsChanged(float rms) { }
            @Override public void onBufferReceived(byte[] b) { }
            @Override public void onEndOfSpeech() { }

            @Override public void onError(int code) {
                // Silence and timeouts are the normal state of a channel left open
                // on purpose; restart quietly rather than reporting them.
                boolean benign = code == SpeechRecognizer.ERROR_NO_MATCH
                        || code == SpeechRecognizer.ERROR_SPEECH_TIMEOUT;
                if (keepListening && benign && !muted) {
                    restartSoon();
                    return;
                }
                if (!benign) {
                    toJs("window.onSpeechError && window.onSpeechError("
                            + JSONObject.quote(errorName(code)) + ")");
                }
                if (keepListening && !muted) restartSoon();
            }

            @Override public void onResults(Bundle results) {
                emit(results, true);
                if (keepListening && !muted) restartSoon();
            }

            @Override public void onPartialResults(Bundle results) { emit(results, false); }
            @Override public void onEvent(int type, Bundle params) { }
        });

        try {
            recognizer.startListening(intent);
        } catch (Exception e) {
            toJs("window.onSpeechError && window.onSpeechError("
                    + JSONObject.quote(String.valueOf(e.getMessage())) + ")");
        }
    }

    private void restartSoon() {
        web.postDelayed(() -> { if (keepListening && !muted) beginListening(); }, 250);
    }

    private void emit(Bundle results, boolean isFinal) {
        ArrayList<String> hits = results == null ? null
                : results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        if (hits == null || hits.isEmpty()) return;
        String text = hits.get(0);
        if (text == null || text.trim().isEmpty()) return;
        toJs("window.onSpeechResult && window.onSpeechResult("
                + JSONObject.quote(text) + ", " + isFinal + ")");
    }

    private void destroyRecognizer() {
        if (recognizer != null) {
            try { recognizer.cancel(); recognizer.destroy(); } catch (Exception ignored) { }
            recognizer = null;
        }
    }

    void release() {
        keepListening = false;
        destroyRecognizer();
        if (tts != null) { tts.stop(); tts.shutdown(); tts = null; }
    }

    private void toJs(final String js) {
        web.post(() -> web.evaluateJavascript(js, null));
    }

    private static String errorName(int code) {
        switch (code) {
            case SpeechRecognizer.ERROR_AUDIO: return "audio";
            case SpeechRecognizer.ERROR_CLIENT: return "client";
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS: return "not-allowed";
            case SpeechRecognizer.ERROR_NETWORK: return "network";
            case SpeechRecognizer.ERROR_NETWORK_TIMEOUT: return "network-timeout";
            case SpeechRecognizer.ERROR_RECOGNIZER_BUSY: return "busy";
            case SpeechRecognizer.ERROR_SERVER: return "server";
            default: return "error-" + code;
        }
    }

    static int requestCode() { return REQ_MIC; }
}
