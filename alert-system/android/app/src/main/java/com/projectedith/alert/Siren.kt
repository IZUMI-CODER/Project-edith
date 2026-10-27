package com.projectedith.alert

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlin.math.PI
import kotlin.math.sin

/** A generated rising-and-falling siren, so the app needs no sound file. */
object Siren {
    private const val RATE = 44100

    /** Playback gain: -10 dB (about half as loud to the ear). 1.0 = full volume. */
    const val GAIN = 0.316f

    fun create(attrs: AudioAttributes): AudioTrack {
        val samples = wail()
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
        track.setVolume(GAIN)
        return track
    }

    /** One 2-second 650 -> 1500 -> 650 Hz cycle, soft-clipped towards a square wave to sound louder. */
    private fun wail(): ShortArray {
        val n = RATE * 2
        val lo = 650.0
        val hi = 1500.0
        val out = ShortArray(n)
        var phase = 0.0
        for (i in 0 until n) {
            val x = i.toDouble() / n
            val f = if (x < 0.5) lo + (hi - lo) * x * 2 else hi - (hi - lo) * (x - 0.5) * 2
            phase += 2 * PI * f / RATE
            val v = (sin(phase) * 2.0).coerceIn(-1.0, 1.0)
            out[i] = (v * 30000).toInt().toShort()
        }
        return out
    }
}
