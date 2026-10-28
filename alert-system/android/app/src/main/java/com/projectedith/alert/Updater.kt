package com.projectedith.alert

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Self-update from the GitHub release. Android only accepts an update signed with the
 * same key as the installed app, so a tampered download can't install. The first update
 * asks the user to confirm; after that the app is its own installer, and Android 12+
 * lets it update itself silently.
 */
object Updater {
    private const val TAG = "Updater"
    private const val CHANNEL_ID = "edith_updates"
    private const val NOTIFICATION_ID = 3
    private const val CHECK_EVERY_MS = 6 * 60 * 60 * 1000L

    private val client = OkHttpClient.Builder().callTimeout(120, TimeUnit.SECONDS).build()
    private val busy = AtomicBoolean(false)

    @Volatile
    var status: String = ""

    /** Checks if one is due (every 6 h); [force] checks now. Safe to call from any thread. */
    fun maybeCheck(ctx: Context, force: Boolean = false) {
        if (BuildConfig.UPDATE_URL.isBlank()) return
        val app = ctx.applicationContext
        if (!force && System.currentTimeMillis() - Prefs.lastUpdateCheck(app) < CHECK_EVERY_MS) return
        if (!busy.compareAndSet(false, true)) return
        thread(name = "edith-updater") {
            try {
                Prefs.setLastUpdateCheck(app, System.currentTimeMillis())
                checkAndInstall(app)
            } catch (e: Exception) {
                Log.w(TAG, "update failed", e)
                status = "Update check failed (${e.message})"
            } finally {
                busy.set(false)
            }
        }
    }

    private fun checkAndInstall(ctx: Context) {
        if (AlarmService.isRinging) {
            status = "Will check for updates after the alarm"
            Prefs.setLastUpdateCheck(ctx, 0)
            return
        }
        status = "Checking for updates…"
        val info = client.newCall(Request.Builder().url(BuildConfig.UPDATE_URL).build()).execute().use { r ->
            check(r.isSuccessful) { "HTTP ${r.code}" }
            JSONObject(r.body!!.string())
        }
        val latest = info.getInt("versionCode")
        if (latest <= BuildConfig.VERSION_CODE) {
            status = "Up to date (build ${BuildConfig.VERSION_CODE})"
            return
        }

        status = "Downloading update (build $latest)…"
        val installer = ctx.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(ctx.packageName)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            }
        }
        val sessionId = installer.createSession(params)
        try {
            installer.openSession(sessionId).use { session ->
                client.newCall(Request.Builder().url(info.getString("apk")).build()).execute().use { r ->
                    check(r.isSuccessful) { "download HTTP ${r.code}" }
                    val body = r.body!!
                    session.openWrite("EdithAlert.apk", 0, body.contentLength()).use { out ->
                        body.byteStream().copyTo(out)
                        session.fsync(out)
                    }
                }
                val result = PendingIntent.getBroadcast(
                    ctx, 30, Intent(ctx, UpdateReceiver::class.java),
                    PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
                session.commit(result.intentSender)
            }
        } catch (e: Exception) {
            runCatching { installer.abandonSession(sessionId) }
            throw e
        }
        status = "Installing update (build $latest)…"
    }

    /** Android wants the user to approve this install: ask with a notification. */
    fun askToConfirm(ctx: Context, confirm: Intent) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "App updates", NotificationManager.IMPORTANCE_DEFAULT),
            )
        }
        confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val tap = PendingIntent.getActivity(
            ctx, 31, confirm, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        nm.notify(
            NOTIFICATION_ID,
            Notification.Builder(ctx, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_alert)
                .setContentTitle("Edith Alert update ready")
                .setContentText("Tap to install the new version.")
                .setContentIntent(tap)
                .setAutoCancel(true)
                .build(),
        )
        // Shows straight away if the app is on screen; otherwise the notification does.
        runCatching { ctx.startActivity(confirm) }
    }
}

/** Receives the result of an update install. */
class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(Intent.EXTRA_INTENT)
                }
                Updater.status = "Update downloaded: tap the notification to install"
                confirm?.let { Updater.askToConfirm(context, it) }
            }
            PackageInstaller.STATUS_SUCCESS -> Updater.status = "Updated"
            else -> Updater.status =
                "Update failed (${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: "unknown"})"
        }
    }
}
