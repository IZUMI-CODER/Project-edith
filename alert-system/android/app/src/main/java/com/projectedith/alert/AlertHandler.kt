package com.projectedith.alert

import android.content.Context

/**
 * One place that acts on an alert, whichever route it came by (the direct link to the
 * website or Google push). Every alert is sent both ways, so the second copy is ignored.
 */
object AlertHandler {

    @Synchronized
    fun handle(ctx: Context, data: Map<String, String>, via: String, detail: String = "") {
        val id = data["id"].orEmpty()
        val type = data["type"].orEmpty().ifBlank { "?" }
        val sentAt = data["sent_at"]?.toLongOrNull()
        val sent = sentAt?.let { "sent ${Prefs.clock(it)}, ${(System.currentTimeMillis() - it) / 1000}s late" }
        val hasVoice = data["voice"] == "1" && id.isNotEmpty()
        val summary = "$type${if (hasVoice) " + voice" else ""} via $via (" +
            listOfNotNull(sent, detail.ifBlank { null }).joinToString(", ") + ")"

        if (id.isNotEmpty() && !Prefs.markSeen(ctx, id)) {
            Prefs.recordReceived(ctx, summary)
            Prefs.recordOutcome(ctx, "duplicate, already handled")
            return
        }
        Prefs.recordReceived(ctx, summary)
        if (Prefs.code(ctx) == null) return Prefs.recordOutcome(ctx, "ignored: phone not paired")

        when (type) {
            "alert" -> Prefs.recordOutcome(
                ctx,
                AlarmService.start(
                    ctx,
                    data["message"].orEmpty().ifBlank { "EMERGENCY ALERT" },
                    data["sender"].orEmpty(),
                    sentAt ?: System.currentTimeMillis(),
                    if (hasVoice) id else null,
                ),
            )
            "stop" -> {
                AlarmService.stop(ctx)
                Prefs.recordOutcome(ctx, "stopped")
            }
            else -> Prefs.recordOutcome(ctx, "ignored: unknown type")
        }
    }
}
