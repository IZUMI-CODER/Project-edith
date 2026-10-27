package com.projectedith.alert

import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class AlertMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val topic = Prefs.topic(this)
        // Skip leftovers from a topic this phone used before re-pairing. Only reject a
        // clearly different topic, so an unexpected "from" format can't block real alerts.
        val from = message.from
        if (topic != null && from != null && from.contains("/topics/") && !from.endsWith("/topics/$topic")) return
        ListenerService.start(this) // in case the phone stopped it

        // Google downgrades "high" to "normal" for apps whose urgent pushes showed nothing;
        // a downgraded push can't start the alarm service from the background.
        AlertHandler.handle(
            this,
            message.data,
            "Google",
            "${priorityName(message.priority)}/${priorityName(message.originalPriority)} priority",
        )
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
