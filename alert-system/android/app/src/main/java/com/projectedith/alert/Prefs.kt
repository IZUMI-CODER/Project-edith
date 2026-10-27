package com.projectedith.alert

import android.content.Context

object Prefs {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("edith", Context.MODE_PRIVATE)

    fun code(ctx: Context): String? = prefs(ctx).getString("code", null)

    fun topic(ctx: Context): String? = code(ctx)?.let { Codes.topic(it) }

    /** Diagnostics: what the last push looked like, shown on the main screen. */
    fun recordReceived(ctx: Context, type: String, from: String) {
        prefs(ctx).edit()
            .putLong("last_at", System.currentTimeMillis())
            .putString("last_type", type)
            .putString("last_from", from)
            .apply()
    }

    fun lastReceived(ctx: Context): Triple<Long, String, String>? {
        val p = prefs(ctx)
        val at = p.getLong("last_at", 0L)
        if (at == 0L) return null
        return Triple(at, p.getString("last_type", "").orEmpty(), p.getString("last_from", "").orEmpty())
    }

    fun setCode(ctx: Context, code: String?) {
        prefs(ctx).edit().apply { if (code == null) remove("code") else putString("code", Codes.normalize(code)) }.apply()
    }
}
