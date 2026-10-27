package com.projectedith.alert

import java.security.MessageDigest

/**
 * Pairing codes, mirroring alert-system/worker/src/codes.js. The phone never needs the
 * server secret: it only checks the code's check character and derives its push topic.
 */
object Codes {
    const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    fun normalize(code: String): String =
        code.uppercase()
            .filter { it in '0'..'9' || it in 'A'..'Z' }
            .replace('O', '0')
            .replace('I', '1')
            .replace('L', '1')

    fun format(code: String): String = normalize(code).chunked(4).joinToString("-")

    fun isValid(code: String): Boolean {
        val c = normalize(code)
        if (c.length != 16 || c.any { it !in ALPHABET }) return false
        return checkChar(c.substring(0, 15)) == c[15]
    }

    fun topic(code: String): String =
        "edith-" + sha256("edith-topic-v1:" + normalize(code)).joinToString("") { "%02x".format(it) }

    private fun checkChar(body: String): Char =
        ALPHABET[(sha256("edith-check-v1:$body")[0].toInt() and 0xff) shr 3]

    private fun sha256(text: String): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
}
