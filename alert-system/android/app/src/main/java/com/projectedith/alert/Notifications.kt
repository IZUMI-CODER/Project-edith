package com.projectedith.alert

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon

object Notifications {
    const val CHANNEL_ID = "edith_alarm"
    const val ALARM_ID = 1

    fun ensureChannel(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(CHANNEL_ID, "Emergency alarms", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Alerts sent from the Edith Alert website"
            setSound(null, null) // AlarmService plays the siren itself on the alarm stream
            enableVibration(false)
            setBypassDnd(true)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        nm.createNotificationChannel(channel)
    }

    /**
     * The alarm notification. With [startAlarm] the full-screen screen starts the siren itself;
     * that is the fallback for when Android refuses to start the alarm service from the background.
     */
    fun build(ctx: Context, info: AlertInfo, startAlarm: Boolean): Notification {
        val open = PendingIntent.getActivity(
            ctx,
            if (startAlarm) 2 else 1,
            AlertActivity.intent(ctx, info, startAlarm),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val title = if (info.from.isBlank()) "🚨 ALERT" else "🚨 ALERT from ${info.from}"
        val builder = Notification.Builder(ctx, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_alert)
            .setColor(0xFFDC2626.toInt())
            .setContentTitle(title)
            .setContentText(info.message)
            .setStyle(Notification.BigTextStyle().bigText(info.message))
            .setCategory(Notification.CATEGORY_ALARM)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setOngoing(true)
            .setContentIntent(open)
            .setFullScreenIntent(open, true)
        if (!startAlarm) {
            val stop = PendingIntent.getService(
                ctx, 3,
                Intent(ctx, AlarmService::class.java).setAction(AlarmService.ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE,
            )
            builder.addAction(
                Notification.Action.Builder(Icon.createWithResource(ctx, R.drawable.ic_alert), "Dismiss", stop).build(),
            )
        }
        return builder.build()
    }

    fun showFallback(ctx: Context, info: AlertInfo) {
        ensureChannel(ctx)
        ctx.getSystemService(NotificationManager::class.java).notify(ALARM_ID, build(ctx, info, startAlarm = true))
    }
}

data class AlertInfo(val message: String, val from: String, val sentAt: Long)
