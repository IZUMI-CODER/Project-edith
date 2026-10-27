package com.projectedith.alert

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.os.Handler
import android.os.Looper
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/** Generated alarm sounds (no sound files) and the volume curve the app's slider uses. */
object Sounds {
    private const val RATE = 44100

    val CHOICES = listOf("chime" to "Chime (gentle)", "beeps" to "Beeps", "siren" to "Siren")

    /** Slider 5..100 % -> gain on a -40..0 dB curve, so each step sounds even. */
    fun gain(percent: Int): Float = 10.0.pow(-40.0 * (1 - percent.coerceIn(5, 100) / 100.0) / 20).toFloat()

    fun create(attrs: AudioAttributes, sound: String, gain: Float): AudioTrack {
        val samples = when (sound) {
            "beeps" -> beeps()
            "siren" -> siren()
            else -> chime()
        }
        val track = AudioTrack.Builder()
            .setAudioAttributes(attrs)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build(),
            )
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(samples.size * 2)
            .build()
        check(track.state == AudioTrack.STATE_NO_STATIC_DATA || track.state == AudioTrack.STATE_INITIALIZED) {
            "AudioTrack failed to initialise"
        }
        track.write(samples, 0, samples.size)
        track.setLoopPoints(0, samples.size, -1)
        track.setVolume(gain)
        return track
    }

    /** Plays [sound] for 3 s exactly as an alert would (alarm stream at max), then restores. */
    fun preview(ctx: Context, sound: String, gain: Float) {
        val audio = ctx.getSystemService(AudioManager::class.java)
        val before = audio.getStreamVolume(AudioManager.STREAM_ALARM)
        runCatching { audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0) }
        val attrs = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        val track = runCatching { create(attrs, sound, gain).also { it.play() } }.getOrNull()
        Handler(Looper.getMainLooper()).postDelayed({
            track?.run { runCatching { stop() }; release() }
            runCatching { audio.setStreamVolume(AudioManager.STREAM_ALARM, before, 0) }
        }, 3000)
    }

    /** "Ding-dong": two soft bell tones (E5 then C5) with a pause, 2.4 s loop. */
    private fun chime(): ShortArray {
        val out = DoubleArray((RATE * 2.4).toInt())
        bell(out, 0.0, 659.25)
        bell(out, 0.55, 523.25)
        return toPcm(out)
    }

    private fun bell(out: DoubleArray, startSec: Double, f: Double) {
        val start = (startSec * RATE).toInt()
        for (i in 0 until min(out.size - start, (RATE * 1.6).toInt())) {
            val t = i.toDouble() / RATE
            val attack = min(1.0, t / 0.005)
            val tone = sin(2 * PI * f * t) + 0.35 * sin(2 * PI * 2 * f * t) * exp(-t * 3) + 0.15 * sin(2 * PI * 3 * f * t) * exp(-t * 5)
            out[start + i] += 0.6 * attack * exp(-t * 2.2) * tone
        }
    }

    /** Three short 880 Hz beeps, then a pause; 1.6 s loop. Soft edges, no clicks. */
    private fun beeps(): ShortArray {
        val out = DoubleArray((RATE * 1.6).toInt())
        for (b in 0 until 3) {
            val start = (b * 0.25 * RATE).toInt()
            val len = (0.15 * RATE).toInt()
            for (i in 0 until len) {
                val t = i.toDouble() / RATE
                val edge = min(1.0, min(t, (len - i).toDouble() / RATE) / 0.008)
                out[start + i] = 0.8 * edge * sin(2 * PI * 880 * t)
            }
        }
        return toPcm(out)
    }

    /** Rising and falling 650-1300 Hz wail (pure tone, no clipping); 2 s loop. */
    private fun siren(): ShortArray {
        val n = RATE * 2
        val out = DoubleArray(n)
        var phase = 0.0
        for (i in 0 until n) {
            val x = i.toDouble() / n
            val f = if (x < 0.5) 650 + 650 * x * 2 else 1300 - 650 * (x - 0.5) * 2
            phase += 2 * PI * f / RATE
            out[i] = 0.8 * sin(phase)
        }
        return toPcm(out)
    }

    private fun toPcm(x: DoubleArray): ShortArray =
        ShortArray(x.size) { (x[it].coerceIn(-1.0, 1.0) * 32000).toInt().toShort() }
}
