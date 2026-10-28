package com.projectedith.alert

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.AudioTrack
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import kotlin.concurrent.thread

/**
 * Rings until dismissed (or for MAX_RING_MS). Plays on the alarm stream, which the
 * silent/vibrate switch doesn't mute, turns that stream to max, and with Do Not Disturb
 * access lets alarms through DND for as long as it rings. Everything is restored after.
 */
class AlarmService : Service() {

    companion object {
        const val ACTION_START = "com.projectedith.alert.START"
        const val ACTION_STOP = "com.projectedith.alert.STOP"
        const val EXTRA_VOICE_ID = "voice_id"
        const val ACTION_REPLAY_VOICE = "com.projectedith.alert.REPLAY_VOICE"

        /** True once a voice message has downloaded and can be replayed. */
        @Volatile
        var voiceReady = false
            private set

        fun replayVoice(ctx: Context) {
            runCatching { ctx.startService(Intent(ctx, AlarmService::class.java).setAction(ACTION_REPLAY_VOICE)) }
        }
        private const val CHIME_BEFORE_VOICE_MS = 5000L
        private const val WAIT_FOR_VOICE_MS = 20_000L
        const val ACTION_DISMISS = "com.projectedith.alert.DISMISS"
        private const val MAX_RING_MS = 10 * 60 * 1000L
        private const val TAG = "AlarmService"

        private val http by lazy { OkHttpClient() }

        @Volatile
        var isRinging = false
            private set

        @Volatile
        var current: AlertInfo? = null
            private set

        /** Set by AlertActivity so it can close when the alarm stops from anywhere. */
        var onStopped: (() -> Unit)? = null

        /** Starts ringing; returns what happened, for the diagnostics line. */
        fun start(ctx: Context, message: String, from: String, sentAt: Long, voiceId: String? = null): String {
            val info = AlertInfo(message, from, sentAt)
            val intent = Intent(ctx, AlarmService::class.java)
                .setAction(ACTION_START)
                .putExtra(AlertActivity.EXTRA_MESSAGE, message)
                .putExtra(AlertActivity.EXTRA_FROM, from)
                .putExtra(AlertActivity.EXTRA_SENT_AT, sentAt)
                .putExtra(EXTRA_VOICE_ID, voiceId)
            val already = isRinging
            try {
                ctx.startForegroundService(intent)
                return if (already) "already ringing, message updated" else "ringing"
            } catch (e: Exception) {
                // Android 12+ refuses background starts unless the push kept its high
                // priority. An alarm-clock alarm is always allowed to start the alarm, and
                // the full-screen notification is a second way in.
                Log.w(TAG, "foreground start refused, using alarm-clock fallback", e)
                val viaAlarm = ringViaAlarmClock(ctx, intent, info)
                Notifications.showFallback(ctx, info)
                return if (viaAlarm) {
                    "background start blocked, ringing via alarm clock"
                } else {
                    "background start blocked (${e.javaClass.simpleName}), alarm clock not allowed, showed notification"
                }
            }
        }

        private fun ringViaAlarmClock(ctx: Context, intent: Intent, info: AlertInfo): Boolean {
            val am = ctx.getSystemService(AlarmManager::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !am.canScheduleExactAlarms()) return false
            return try {
                val ring = PendingIntent.getForegroundService(
                    ctx, 10, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
                val show = PendingIntent.getActivity(
                    ctx, 11, AlertActivity.intent(ctx, info, startAlarm = false),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
                am.setAlarmClock(AlarmManager.AlarmClockInfo(System.currentTimeMillis() + 1000, show), ring)
                true
            } catch (e: Exception) {
                Log.w(TAG, "alarm-clock fallback failed", e)
                false
            }
        }

        /** User dismissed: the chime stops, but a voice message still plays once in full. */
        fun dismiss(ctx: Context) {
            runCatching { ctx.startService(Intent(ctx, AlarmService::class.java).setAction(ACTION_DISMISS)) }
                .onFailure { stop(ctx) }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, AlarmService::class.java))
            ctx.getSystemService(NotificationManager::class.java).cancel(Notifications.ALARM_ID)
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private val timeout = Runnable { stopSelf() }
    private val attrs = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ALARM)
        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
        .build()

    private var track: AudioTrack? = null
    private var player: MediaPlayer? = null
    private var vibrator: Vibrator? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var focusRequest: AudioFocusRequest? = null
    private var savedVolume: Int? = null
    private var savedFilter: Int? = null
    private var voiceClip: VoiceClip? = null
    private var voiceId: String? = null

    private var dismissed = false
    private var voiceDue = false // the chime has had its 5 s
    private var voiceNoted = false

    /**
     * Chime for 5 s, then the voice message, then chime 5 s, voice, ... until dismissed.
     * After Dismiss the chime stops and the voice plays once more in full, then all stops.
     */
    private val playVoice = Runnable {
        val clip = voiceClip ?: return@Runnable
        if (clip.isPlaying) return@Runnable
        track?.pause()
        player?.pause()
        if (!voiceNoted) Prefs.appendNote(this, "voice started")
        clip.play(attrs, voiceGain()) {
            if (!voiceNoted) Prefs.appendNote(this, "voice finished")
            voiceNoted = true
            onVoiceFinished()
        }
    }

    /** Speech is far quieter than a steady chime at the same gain: +20 dB over the slider. */
    private fun voiceGain() = minOf(1f, Sounds.gain(Prefs.volume(this)) * 10f)

    private val chimeDone = Runnable {
        voiceDue = true
        handler.post(playVoice)
    }

    private fun onVoiceFinished() {
        if (dismissed) {
            stopSelf()
        } else {
            track?.play()
            player?.start()
            handler.postDelayed(playVoice, CHIME_BEFORE_VOICE_MS)
        }
    }

    private fun dismissNow() {
        if (dismissed) return stopSelf() // second Dismiss: stop the voice too
        dismissed = true
        handler.removeCallbacks(chimeDone)
        handler.removeCallbacks(playVoice)
        track?.pause()
        player?.pause()
        vibrator?.cancel()
        onStopped?.invoke() // close the alert screen
        val clip = voiceClip
        when {
            clip != null && clip.isPlaying -> Unit // let it finish, then stop
            clip != null -> handler.post(playVoice)
            voiceId != null -> handler.postDelayed(timeout, WAIT_FOR_VOICE_MS) // still downloading
            else -> stopSelf()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_REPLAY_VOICE) {
            if (isRinging) handler.post(playVoice)
            return START_NOT_STICKY
        }
        if (intent?.action == ACTION_DISMISS) {
            if (isRinging) dismissNow() else stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.action != ACTION_START) {
            stopSelf()
            return START_NOT_STICKY
        }
        val info = AlertInfo(
            intent.getStringExtra(AlertActivity.EXTRA_MESSAGE).orEmpty().ifBlank { "EMERGENCY ALERT" },
            intent.getStringExtra(AlertActivity.EXTRA_FROM).orEmpty(),
            intent.getLongExtra(AlertActivity.EXTRA_SENT_AT, System.currentTimeMillis()),
        )
        current = info
        Notifications.ensureChannel(this)
        val notification = Notifications.build(this, info, startAlarm = false)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(Notifications.ALARM_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
        } else {
            startForeground(Notifications.ALARM_ID, notification)
        }
        if (dismissed) {
            // A new alert arrived while the last voice message was finishing: ring again.
            dismissed = false
            track?.play()
            player?.start()
        }
        if (!isRinging) startRinging()
        intent.getStringExtra(EXTRA_VOICE_ID)?.let { if (it != voiceId) loadVoice(it) }
        handler.removeCallbacks(timeout)
        handler.postDelayed(timeout, MAX_RING_MS)
        return START_NOT_STICKY
    }

    private fun startRinging() {
        isRinging = true
        val audio = getSystemService(AudioManager::class.java)
        val nm = getSystemService(NotificationManager::class.java)

        if (nm.isNotificationPolicyAccessGranted && alarmsBlockedByDnd(nm)) {
            savedFilter = nm.currentInterruptionFilter
            nm.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALARMS)
        }

        try {
            savedVolume = audio.getStreamVolume(AudioManager.STREAM_ALARM)
            audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0)
        } catch (e: SecurityException) {
            Log.w(TAG, "could not raise alarm volume", e)
            savedVolume = null
        }

        focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attrs)
            .build()
            .also { audio.requestAudioFocus(it) }

        try {
            track = Sounds.create(attrs, Prefs.sound(this), Sounds.gain(Prefs.volume(this))).also { it.play() }
        } catch (e: Exception) {
            Log.w(TAG, "siren failed, falling back to the system alarm sound", e)
            try {
                player = MediaPlayer().apply {
                    setAudioAttributes(attrs)
                    setDataSource(this@AlarmService, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM))
                    isLooping = true
                    Sounds.gain(Prefs.volume(this@AlarmService)).let { setVolume(it, it) }
                    prepare()
                    start()
                }
            } catch (e2: Exception) {
                Log.e(TAG, "no alarm sound available", e2)
            }
        }

        val v = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            getSystemService(VibratorManager::class.java).defaultVibrator
        } else {
            getSystemService(Vibrator::class.java)
        }
        // Deprecated on API 33, but the AudioAttributes overload is what marks it as an alarm buzz.
        v.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 800, 400), 0), attrs)
        vibrator = v

        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "edith:alarm")
            .apply { acquire(MAX_RING_MS + 60_000) }

        voiceDue = false
        handler.postDelayed(chimeDone, CHIME_BEFORE_VOICE_MS)
    }

    /** Downloads the voice message (kept by the website for 15 min) while the chime plays. */
    private fun loadVoice(id: String) {
        voiceId = id
        voiceNoted = false
        val topic = Prefs.topic(this) ?: return
        val base = BuildConfig.SERVER_URL.trimEnd('/')
        if (base.isBlank()) return Prefs.appendNote(this, "voice: no server address in this build")
        val file = File(cacheDir, "voice-message")
        thread(name = "edith-voice") {
            repeat(3) { attempt ->
                try {
                    val request = Request.Builder().url("$base/api/voice/$id?topic=$topic").build()
                    http.newCall(request).execute().use { r ->
                        check(r.isSuccessful) { "HTTP ${r.code}" }
                        file.outputStream().use { out -> r.body!!.byteStream().copyTo(out) }
                    }
                    Prefs.appendNote(this, "voice downloaded (${file.length() / 1024} KB)")
                    handler.post { if (voiceId == id && isRinging) startVoice(file) }
                    return@thread
                } catch (e: Exception) {
                    Log.w(TAG, "voice download attempt ${attempt + 1} failed", e)
                    if (attempt == 2) {
                        Prefs.appendNote(this, "voice download failed (${e.message})")
                        handler.post { if (dismissed) stopSelf() }
                    }
                    Thread.sleep(2000)
                }
            }
        }
    }

    private fun startVoice(file: File) {
        voiceClip?.cancel()
        voiceClip = try {
            VoiceClip.load(file)
        } catch (e: Exception) {
            Log.w(TAG, "can't read voice message", e)
            Prefs.appendNote(this, "voice can't be read (${e.javaClass.simpleName})")
            null
        }
        val clip = voiceClip
        if (clip == null) {
            if (dismissed) stopSelf()
            return
        }
        voiceReady = true
        Prefs.appendNote(this, "voice ready: ${clip.description}")
        if (voiceDue || dismissed) {
            handler.removeCallbacks(timeout)
            handler.post(playVoice)
            if (!dismissed) handler.postDelayed(timeout, MAX_RING_MS)
        }
    }

    private fun alarmsBlockedByDnd(nm: NotificationManager): Boolean = when (nm.currentInterruptionFilter) {
        NotificationManager.INTERRUPTION_FILTER_NONE -> true
        NotificationManager.INTERRUPTION_FILTER_PRIORITY ->
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
                nm.notificationPolicy.priorityCategories and NotificationManager.Policy.PRIORITY_CATEGORY_ALARMS == 0
        else -> false
    }

    override fun onDestroy() {
        handler.removeCallbacks(timeout)
        handler.removeCallbacks(playVoice)
        handler.removeCallbacks(chimeDone)
        dismissed = false
        voiceClip?.cancel()
        voiceClip = null
        voiceId = null
        voiceReady = false
        track?.run { runCatching { stop() }; release() }
        player?.run { runCatching { stop() }; release() }
        vibrator?.cancel()
        val audio = getSystemService(AudioManager::class.java)
        savedVolume?.let { runCatching { audio.setStreamVolume(AudioManager.STREAM_ALARM, it, 0) } }
        focusRequest?.let { audio.abandonAudioFocusRequest(it) }
        val nm = getSystemService(NotificationManager::class.java)
        savedFilter?.let { if (nm.isNotificationPolicyAccessGranted) runCatching { nm.setInterruptionFilter(it) } }
        wakeLock?.let { if (it.isHeld) it.release() }
        isRinging = false
        current = null
        onStopped?.invoke()
        super.onDestroy()
    }
}
