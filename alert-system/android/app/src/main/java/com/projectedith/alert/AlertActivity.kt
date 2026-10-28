package com.projectedith.alert

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.text.format.DateFormat
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import java.util.Date

/** Full-screen red alarm screen; shows over the lock screen and turns the screen on. */
class AlertActivity : Activity() {

    companion object {
        const val EXTRA_MESSAGE = "message"
        const val EXTRA_FROM = "from"
        const val EXTRA_SENT_AT = "sent_at"
        private const val EXTRA_START_ALARM = "start_alarm"

        fun intent(ctx: Context, info: AlertInfo, startAlarm: Boolean): Intent =
            Intent(ctx, AlertActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra(EXTRA_MESSAGE, info.message)
                .putExtra(EXTRA_FROM, info.from)
                .putExtra(EXTRA_SENT_AT, info.sentAt)
                .putExtra(EXTRA_START_ALARM, startAlarm)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_alert)

        findViewById<Button>(R.id.replay).setOnClickListener { AlarmService.replayVoice(this) }
        findViewById<Button>(R.id.dismiss).setOnClickListener {
            AlarmService.dismiss(this) // a voice message still plays once
            finish()
        }
        AlarmService.onStopped = { runOnUiThread { finish() } }
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent) {
        val info = AlertInfo(
            intent.getStringExtra(EXTRA_MESSAGE).orEmpty().ifBlank { "EMERGENCY ALERT" },
            intent.getStringExtra(EXTRA_FROM).orEmpty(),
            intent.getLongExtra(EXTRA_SENT_AT, System.currentTimeMillis()),
        )
        if (intent.getBooleanExtra(EXTRA_START_ALARM, false)) {
            // Fallback path: the service couldn't start from the background, but it can now.
            intent.removeExtra(EXTRA_START_ALARM)
            if (!AlarmService.isRinging) AlarmService.start(this, info.message, info.from, info.sentAt)
        }
        findViewById<TextView>(R.id.message).text = info.message
        val time = DateFormat.getTimeFormat(this).format(Date(info.sentAt))
        findViewById<TextView>(R.id.details).text =
            if (info.from.isBlank()) "Sent at $time" else "From ${info.from} at $time"
    }

    // Show the replay button once a voice message has arrived.
    private val voiceCheck = object : Runnable {
        override fun run() {
            findViewById<Button>(R.id.replay).visibility = if (AlarmService.voiceReady) View.VISIBLE else View.GONE
            window.decorView.postDelayed(this, 1000)
        }
    }

    override fun onResume() {
        super.onResume()
        window.decorView.post(voiceCheck)
    }

    override fun onPause() {
        window.decorView.removeCallbacks(voiceCheck)
        super.onPause()
    }

    override fun onDestroy() {
        AlarmService.onStopped = null
        super.onDestroy()
    }
}
