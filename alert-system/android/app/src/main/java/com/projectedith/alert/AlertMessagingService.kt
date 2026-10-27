package com.projectedith.alert

import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class AlertMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        // Google downgrades "high" to "normal" for apps whose urgent pushes showed nothing;
        // a downgraded push can't start the alarm service from the background.
        val sentAt = data["sent_at"]?.toLongOrNull()
        val sent = sentAt?.let { "sent ${Prefs.clock(it)}, ${(System.currentTimeMillis() - it) / 1000}s late, " }.orEmpty()
        Prefs.recordReceived(
            this,
            "${data["type"] ?: "?"} ($sent${priorityName(message.priority)}/${priorityName(message.originalPriority)} priority)",
        )

        val topic = Prefs.topic(this) ?: return Prefs.recordOutcome(this, "ignored: phone not paired")
        ListenerService.start(this) // in case the phone stopped it
        // Skip leftovers from a topic this phone used before re-pairing. Only reject a
        // clearly different topic, so an unexpected "from" format can't block real alerts.
        val from = message.from
        if (from != null && from.contains("/topics/") && !from.endsWith("/topics/$topic")) {
            return Prefs.recordOutcome(this, "ignored: for another code ($from)")
        }

        when (data["type"]) {
            "alert" -> Prefs.recordOutcome(
                this,
                AlarmService.start(
                    this,
                    data["message"].orEmpty().ifBlank { "EMERGENCY ALERT" },
                    data["sender"].orEmpty(),
                    data["sent_at"]?.toLongOrNull() ?: System.currentTimeMillis(),
                ),
            )
            "stop" -> {
                AlarmService.stop(this)
                Prefs.recordOutcome(this, "stopped")
            }
            else -> Prefs.recordOutcome(this, "ignored: unknown type")
        }
    }

    private fun priorityName(p: Int) = when (p) {
        RemoteMessage.PRIORITY_HIGH -> "high"
        RemoteMessage.PRIORITY_NORMAL -> "normal"
        else -> "unknown"
    }

    override fun onNewToken(token: String) {
        Prefs.topic(this)?.let { FirebaseMessaging.getInstance().subscribeToTopic(it) }
    }
}
