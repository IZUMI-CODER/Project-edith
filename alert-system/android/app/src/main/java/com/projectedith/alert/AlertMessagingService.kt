package com.projectedith.alert

import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class AlertMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        // Only react to this phone's own topic; anything else is ignored.
        val topic = Prefs.topic(this) ?: return
        if (message.from != "/topics/$topic") return

        val data = message.data
        when (data["type"]) {
            "alert" -> AlarmService.start(
                this,
                data["message"].orEmpty().ifBlank { "EMERGENCY ALERT" },
                data["from"].orEmpty(),
                data["sent_at"]?.toLongOrNull() ?: System.currentTimeMillis(),
            )
            "stop" -> AlarmService.stop(this)
        }
    }

    override fun onNewToken(token: String) {
        Prefs.topic(this)?.let { FirebaseMessaging.getInstance().subscribeToTopic(it) }
    }
}
