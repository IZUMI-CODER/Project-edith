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
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * A quiet, always-on foreground service. It does nothing itself; it exists so that
 * phones with aggressive power managers (ZTE, Xiaomi, Oppo, ...) don't freeze the app,
 * because Google drops pushes for a frozen app instead of queueing them.
 */
class ListenerService : Service() {

    companion object {
        private const val CHANNEL_ID = "edith_listening"
        private const val NOTIFICATION_ID = 2
        private const val TAG = "ListenerService"

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

    override fun onBind(intent: Intent?): IBinder? = null

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
        return START_STICKY
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
