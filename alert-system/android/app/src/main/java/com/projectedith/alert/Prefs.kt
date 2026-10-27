package com.projectedith.alert

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object Prefs {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("edith", Context.MODE_PRIVATE)

    fun code(ctx: Context): String? = prefs(ctx).getString("code", null)

    fun topic(ctx: Context): String? = code(ctx)?.let { Codes.topic(it) }

    /** Diagnostics: the last few pushes and what the app did with each, newest first. */
    fun recordReceived(ctx: Context, summary: String) {
        val line = "${clock(System.currentTimeMillis())} got: $summary → …"
        save(ctx, (listOf(line) + history(ctx)).take(5))
    }

    fun recordOutcome(ctx: Context, outcome: String) {
        val lines = history(ctx).toMutableList()
        if (lines.isNotEmpty() && lines[0].endsWith("→ …")) lines[0] = lines[0].removeSuffix("…") + outcome
        save(ctx, lines)
    }

    fun history(ctx: Context): List<String> =
        prefs(ctx).getString("history", "").orEmpty().split("\n").filter { it.isNotBlank() }

    /** Remembers alert ids; returns false if this one was already handled. */
    fun markSeen(ctx: Context, id: String): Boolean {
        val seen = prefs(ctx).getString("seen_ids", "").orEmpty().split(",").filter { it.isNotBlank() }
        if (id in seen) return false
        prefs(ctx).edit().putString("seen_ids", (listOf(id) + seen).take(30).joinToString(",")).apply()
        return true
    }

    @Volatile
    var directStatus: String = "starting…"

    fun clock(at: Long): String = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date(at))

    private fun save(ctx: Context, lines: List<String>) {
        prefs(ctx).edit().putString("history", lines.joinToString("\n")).apply()
    }

    fun sound(ctx: Context): String = prefs(ctx).getString("sound", "chime") ?: "chime"

    fun setSound(ctx: Context, sound: String) = prefs(ctx).edit().putString("sound", sound).apply()

    /** Alarm volume in percent (5..100); 50 is about 20 dB below full. */
    fun volume(ctx: Context): Int = prefs(ctx).getInt("volume", 50)

    fun setVolume(ctx: Context, percent: Int) = prefs(ctx).edit().putInt("volume", percent).apply()

    fun setCode(ctx: Context, code: String?) {
        prefs(ctx).edit().apply { if (code == null) remove("code") else putString("code", Codes.normalize(code)) }.apply()
    }
}
