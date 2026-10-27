package com.projectedith.alert

import android.content.Context

object Prefs {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("edith", Context.MODE_PRIVATE)

    fun code(ctx: Context): String? = prefs(ctx).getString("code", null)

    fun topic(ctx: Context): String? = code(ctx)?.let { Codes.topic(it) }

    fun setCode(ctx: Context, code: String?) {
        prefs(ctx).edit().apply { if (code == null) remove("code") else putString("code", Codes.normalize(code)) }.apply()
    }
}
