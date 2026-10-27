package com.projectedith.alert

import android.content.Context

object Prefs {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("edith", Context.MODE_PRIVATE)

    fun code(ctx: Context): String? = prefs(ctx).getString("code", null)

    fun topic(ctx: Context): String? = code(ctx)?.let { Codes.topic(it) }

    /** Diagnostics: what the last push looked like and what the app did with it. */
    fun recordReceived(ctx: Context, summary: String) {
        prefs(ctx).edit()
            .putLong("last_at", System.currentTimeMillis())
            .putString("last_summary", summary)
            .putString("last_outcome", "")
            .apply()
    }

    fun recordOutcome(ctx: Context, outcome: String) {
        prefs(ctx).edit().putString("last_outcome", outcome).apply()
    }

    fun lastReceived(ctx: Context): Pair<Long, String>? {
        val p = prefs(ctx)
        val at = p.getLong("last_at", 0L)
        if (at == 0L) return null
        val outcome = p.getString("last_outcome", "").orEmpty()
        return at to (p.getString("last_summary", "").orEmpty() + if (outcome.isBlank()) "" else " → $outcome")
    }

    fun setCode(ctx: Context, code: String?) {
        prefs(ctx).edit().apply { if (code == null) remove("code") else putString("code", Codes.normalize(code)) }.apply()
    }
}
