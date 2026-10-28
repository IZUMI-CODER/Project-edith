package com.projectedith.alert

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

class VoiceClipTest {
    /** Same layout the website's toWav() produces: 16 kHz, mono, 16-bit. */
    private fun wav(seconds: Double, rate: Int = 16000): File {
        val samples = (seconds * rate).toInt()
        val buf = ByteBuffer.allocate(44 + samples * 2).order(ByteOrder.LITTLE_ENDIAN)
        buf.put("RIFF".toByteArray()).putInt(36 + samples * 2).put("WAVE".toByteArray())
        buf.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(rate).putInt(rate * 2)
            .putShort(2).putShort(16)
        buf.put("data".toByteArray()).putInt(samples * 2)
        repeat(samples) { buf.putShort((it % 100).toShort()) }
        return File.createTempFile("voice", ".wav").apply { writeBytes(buf.array()); deleteOnExit() }
    }

    @Test
    fun readsTheWebsitesWav() {
        assertEquals("WAV 16000 Hz, 7.5 s", VoiceClip.load(wav(7.5)).description)
    }

    @Test
    fun otherFormatsFallBackToMediaPlayer() {
        val mp4 = File.createTempFile("voice", ".m4a").apply {
            writeBytes(byteArrayOf(0, 0, 0, 24) + "ftypM4A ".toByteArray() + ByteArray(64))
            deleteOnExit()
        }
        assertTrue(VoiceClip.load(mp4).description.startsWith("not WAV (ftyp)"))
    }
}
