package com.projectedith.alert

import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class AlertMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        Prefs.recordReceived(this, data["type"].orEmpty(), message.from.orEmpty())

        val topic = Prefs.topic(this) ?: return
        // Skip leftovers from a topic this phone used before re-pairing. Only reject a
        // clearly different topic, so an unexpected "from" format can't block real alerts.
        val from = message.from
        if (from != null && from.contains("/topics/") && !from.endsWith("/topics/$topic")) return

        when (data["type"]) {
            "alert" -> AlarmService.start(
                this,
                data["message"].orEmpty().ifBlank { "EMERGENCY ALERT" },
                data["sender"].orEmpty(),
                data["sent_at"]?.toLongOrNull() ?: System.currentTimeMillis(),
            )
            "stop" -> AlarmService.stop(this)
        }
    }

    override fun onNewToken(token: String) {
        Prefs.topic(this)?.let { FirebaseMessaging.getInstance().subscribeToTopic(it) }
    }
}
