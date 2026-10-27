package com.projectedith.alert

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Always-on foreground service that
 *  1. keeps phones with aggressive power managers (ZTE, Xiaomi, ...) from freezing the
 *     app, since Google drops pushes for a frozen app instead of queueing them, and
 *  2. holds a direct WebSocket to the website. The website pings it every 30 s, so Wi-Fi
 *     extenders that silently cut "idle" connections (which breaks Google push) never
 *     see it as idle. Alerts arrive both ways; AlertHandler drops the duplicate.
 */
class ListenerService : Service() {

    companion object {
        private const val CHANNEL_ID = "edith_listening"
        private const val NOTIFICATION_ID = 2
        private const val TAG = "ListenerService"
        private const val SILENCE_LIMIT_MS = 75_000L // server pings every 30 s
        private const val WATCHDOG_MS = 30_000L

        fun start(ctx: Context) {
            if (Prefs.code(ctx) == null) return
            try {
                ctx.startForegroundService(Intent(ctx, ListenerService::class.java))
            } catch (e: Exception) {
                Log.w(TAG, "could not start listener", e)
            }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, ListenerService::class.java))
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var socket: WebSocket? = null
    private var socketTopic: String? = null
    private var attempts = 0
    @Volatile private var lastHeard = 0L
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private val reconnect = Runnable { connect() }
    private val watchdog = object : Runnable {
        override fun run() {
            val silentFor = SystemClock.elapsedRealtime() - lastHeard
            if (socket != null && lastHeard > 0 && silentFor > SILENCE_LIMIT_MS) {
                Log.i(TAG, "no ping for ${silentFor / 1000}s, reconnecting")
                connect()
            } else if (socketTopic != Prefs.topic(this@ListenerService)) {
                connect() // paired with a different code
            }
            handler.postDelayed(this, WATCHDOG_MS)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val cm = getSystemService(ConnectivityManager::class.java)
        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                // New Wi-Fi or mobile network: the old connection is dead, reconnect now.
                handler.post { connect() }
            }
        }.also { runCatching { cm.registerDefaultNetworkCallback(it) } }
        handler.postDelayed(watchdog, WATCHDOG_MS)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Ready for alerts", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Keeps Edith Alert running so alerts can't be missed"
                    setShowBadge(false)
                },
            )
        }
        val open = PendingIntent.getActivity(
            this, 20, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_alert)
            .setContentTitle("Edith Alert is ready")
            .setContentText("This phone will ring when an alert is sent.")
            .setOngoing(true)
            .setContentIntent(open)
            .build()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } catch (e: Exception) {
            Log.w(TAG, "startForeground refused", e)
            stopSelf()
            return START_NOT_STICKY
        }
        if (socket == null) connect()
        return START_STICKY
    }

    private fun connect() {
        handler.removeCallbacks(reconnect)
        socket?.cancel()
        socket = null
        val topic = Prefs.topic(this)
        socketTopic = topic
        val base = BuildConfig.SERVER_URL.trimEnd('/')
        if (topic == null || base.isBlank()) {
            Prefs.directStatus = if (base.isBlank()) "not set up in this build" else "not paired"
            return
        }
        Prefs.directStatus = "connecting…"
        val url = base.replaceFirst(Regex("^http"), "ws") + "/api/listen?topic=$topic"
        socket = client.newWebSocket(Request.Builder().url(url).build(), Listener())
    }

    private fun retryLater() {
        val delay = minOf(30_000L, 1_000L shl minOf(attempts, 5))
        attempts++
        handler.removeCallbacks(reconnect)
        handler.postDelayed(reconnect, delay)
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (webSocket !== socket) return
            attempts = 0
            lastHeard = SystemClock.elapsedRealtime()
            Prefs.directStatus = "connected ✓"
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (webSocket !== socket) return
            lastHeard = SystemClock.elapsedRealtime()
            if (text == "ping") return
            try {
                val json = JSONObject(text)
                val data = json.keys().asSequence().associateWith { json.optString(it) }
                AlertHandler.handle(this@ListenerService, data, "direct link")
            } catch (e: Exception) {
                Log.w(TAG, "bad message", e)
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = dropped(webSocket, "closed ($code)")

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
            dropped(webSocket, t.javaClass.simpleName)

        private fun dropped(webSocket: WebSocket, why: String) {
            handler.post {
                if (webSocket !== socket) return@post
                socket = null
                Prefs.directStatus = "reconnecting… ($why)"
                retryLater()
            }
        }
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        networkCallback?.let { cb -> runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(cb) } }
        socket?.close(1000, "bye")
        socket = null
        Prefs.directStatus = "off"
        super.onDestroy()
    }
}

/** Brings the listener back after a reboot or an app update. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            -> ListenerService.start(context)
        }
    }
}
