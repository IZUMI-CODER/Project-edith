package com.projectedith.alert

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import java.io.File
import kotlin.concurrent.thread

/**
 * A downloaded voice message. The website sends 16-bit WAV, which is played straight
 * through an AudioTrack, the same output path as the chime. (MediaPlayer reported
 * "playing" on a ZTE phone but produced no sound.) Anything that isn't WAV falls back
 * to MediaPlayer.
 */
class VoiceClip private constructor(
    private val file: File,
    private val pcm: ShortArray?,
    private val rate: Int,
    private val channels: Int,
    val description: String,
) {
    @Volatile
    var isPlaying = false
        private set

    @Volatile
    private var cancelled = false
    private var media: MediaPlayer? = null

    companion object {
        private const val TAG = "VoiceClip"

        fun load(file: File): VoiceClip {
            val b = file.readBytes()
            fun text(at: Int) = if (at + 4 <= b.size) String(b, at, 4, Charsets.US_ASCII) else ""
            fun u16(at: Int) = (b[at].toInt() and 0xff) or ((b[at + 1].toInt() and 0xff) shl 8)
            fun u32(at: Int) = u16(at) or (u16(at + 2) shl 16)

            if (text(0) != "RIFF" || text(8) != "WAVE") {
                val head = text(4).filter { it.isLetterOrDigit() }.ifBlank { "?" }
                return VoiceClip(file, null, 0, 0, "not WAV ($head), using media player")
            }
            var rate = 16000
            var channels = 1
            var bits = 16
            var pos = 12
            while (pos + 8 <= b.size) {
                val id = text(pos)
                val len = u32(pos + 4)
                if (id == "fmt ") {
                    channels = u16(pos + 10)
                    rate = u32(pos + 12)
                    bits = u16(pos + 22)
                } else if (id == "data") {
                    val start = pos + 8
                    val bytes = minOf(len, b.size - start) and 1.inv()
                    if (bits != 16 || channels !in 1..2) break
                    val pcm = ShortArray(bytes / 2) { u16(start + it * 2).toShort() }
                    val seconds = pcm.size.toDouble() / channels / rate
                    return VoiceClip(file, pcm, rate, channels, "WAV $rate Hz, %.1f s".format(seconds))
                }
                pos += 8 + len + (len and 1)
            }
            return VoiceClip(file, null, 0, 0, "unusual WAV ($bits-bit, $channels ch), using media player")
        }
    }

    /** Plays once; [onDone] runs on the main thread when it ends (not if cancelled). */
    fun play(attrs: AudioAttributes, gain: Float, onDone: () -> Unit) {
        if (isPlaying) return
        isPlaying = true
        cancelled = false
        val main = Handler(Looper.getMainLooper())
        val samples = pcm
        if (samples == null) {
            playWithMediaPlayer(attrs, gain, main, onDone)
            return
        }
        thread(name = "edith-voice-play") {
            var track: AudioTrack? = null
            try {
                val mask = if (channels == 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO
                val minBuffer = AudioTrack.getMinBufferSize(rate, mask, AudioFormat.ENCODING_PCM_16BIT)
                track = AudioTrack.Builder()
                    .setAudioAttributes(attrs)
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(rate)
                            .setChannelMask(mask)
                            .build(),
                    )
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .setBufferSizeInBytes(maxOf(minBuffer, rate * channels)) // ~0.5 s
                    .build()
                track.setVolume(gain)
                track.play()
                var offset = 0
                while (offset < samples.size && !cancelled) {
                    val n = track.write(samples, offset, minOf(2048, samples.size - offset))
                    if (n <= 0) break
                    offset += n
                }
                // Wait for the buffered tail to actually come out of the speaker.
                val frames = samples.size / channels
                val deadline = SystemClock.elapsedRealtime() + 2000 + frames * 1000L / rate
                while (!cancelled && track.playbackHeadPosition < frames && SystemClock.elapsedRealtime() < deadline) {
                    Thread.sleep(30)
                }
            } catch (e: Exception) {
                Log.w(TAG, "voice playback failed", e)
            } finally {
                runCatching { track?.stop() }
                track?.release()
                isPlaying = false
                if (!cancelled) main.post(onDone)
            }
        }
    }

    private fun playWithMediaPlayer(attrs: AudioAttributes, gain: Float, main: Handler, onDone: () -> Unit) {
        try {
            media?.release()
            media = MediaPlayer().apply {
                setAudioAttributes(attrs)
                setDataSource(file.path)
                prepare()
                setVolume(gain, gain)
                setOnCompletionListener {
                    this@VoiceClip.isPlaying = false
                    if (!cancelled) onDone()
                }
                start()
            }
        } catch (e: Exception) {
            Log.w(TAG, "media player failed", e)
            isPlaying = false
            main.post(onDone)
        }
    }

    fun cancel() {
        cancelled = true
        media?.run { runCatching { stop() }; release() }
        media = null
        isPlaying = false
    }
}
