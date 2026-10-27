package com.projectedith.alert

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import com.google.firebase.messaging.FirebaseMessaging

/** Pairing and the one-time permission checklist. */
class MainActivity : Activity() {

    private lateinit var status: TextView
    private lateinit var codeInput: EditText
    private lateinit var pairButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        status = findViewById(R.id.status)
        codeInput = findViewById(R.id.codeInput)
        pairButton = findViewById(R.id.pair)

        pairButton.setOnClickListener { pair() }
        findViewById<Button>(R.id.unpair).setOnClickListener { confirmUnpair() }
        findViewById<Button>(R.id.test).setOnClickListener {
            AlarmService.start(this, "This is a test alarm", "", System.currentTimeMillis())
        }
        findViewById<Button>(R.id.notif).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
            }
        }
        findViewById<Button>(R.id.fullscreen).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                open(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:$packageName")))
            }
        }
        findViewById<Button>(R.id.dnd).setOnClickListener {
            open(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS))
        }
        findViewById<Button>(R.id.battery).setOnClickListener { requestBatteryExemption() }
        setUpSoundControls()

        // Re-assert the subscription on every launch; it is idempotent.
        Prefs.topic(this)?.let { topic ->
            FirebaseMessaging.getInstance().subscribeToTopic(topic).addOnCompleteListener { task ->
                if (!task.isSuccessful) {
                    Toast.makeText(this, "Can't reach Google's push service: ${task.exception?.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private val ticker = object : Runnable {
        override fun run() {
            showLastReceived() // keeps it live while testing
            handler.postDelayed(this, 2000)
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
        handler.post(ticker)
    }

    override fun onPause() {
        handler.removeCallbacks(ticker)
        super.onPause()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refresh()
    }

    private fun pair() {
        val raw = codeInput.text.toString()
        if (!Codes.isValid(raw)) {
            Toast.makeText(this, "That code isn't right. Check it for typos.", Toast.LENGTH_LONG).show()
            return
        }
        val old = Prefs.topic(this)
        val topic = Codes.topic(raw)
        pairButton.isEnabled = false
        status.text = "Connecting…"
        FirebaseMessaging.getInstance().subscribeToTopic(topic).addOnCompleteListener { task ->
            pairButton.isEnabled = true
            if (task.isSuccessful) {
                if (old != null && old != topic) FirebaseMessaging.getInstance().unsubscribeFromTopic(old)
                Prefs.setCode(this, raw)
                codeInput.setText("")
                refresh()
            } else {
                status.text = "Couldn't connect (${task.exception?.message}). Check the internet and try again."
            }
        }
    }

    private fun confirmUnpair() {
        AlertDialog.Builder(this)
            .setMessage("Stop receiving alarms on this phone?")
            .setPositiveButton("Unpair") { _, _ ->
                Prefs.topic(this)?.let { FirebaseMessaging.getInstance().unsubscribeFromTopic(it) }
                Prefs.setCode(this, null)
                ListenerService.stop(this)
                refresh()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun refresh() {
        val code = Prefs.code(this)
        if (code != null) ListenerService.start(this) // idempotent
        status.text = if (code != null) {
            "✅ Paired (${Codes.format(code)}). This phone will ring when an alert is sent to it."
        } else {
            "Not paired yet. Enter the code from the Edith Alert website."
        }
        showLastReceived()
        findViewById<View>(R.id.pairSection).visibility = if (code == null) View.VISIBLE else View.GONE
        findViewById<View>(R.id.unpair).visibility = if (code != null) View.VISIBLE else View.GONE

        val nm = getSystemService(NotificationManager::class.java)
        val pm = getSystemService(PowerManager::class.java)
        setItem(
            R.id.notif, "Notifications",
            Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED,
        )
        setItem(
            R.id.fullscreen, "Full-screen alerts",
            Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE || nm.canUseFullScreenIntent(),
        )
        setItem(R.id.dnd, "Ring during Do Not Disturb", nm.isNotificationPolicyAccessGranted)
        setItem(R.id.battery, "Ignore battery saving", pm.isIgnoringBatteryOptimizations(packageName))
    }

    private fun setUpSoundControls() {
        val group = findViewById<RadioGroup>(R.id.soundGroup)
        val current = Prefs.sound(this)
        Sounds.CHOICES.forEachIndexed { i, (key, title) ->
            group.addView(RadioButton(this).apply {
                id = 1000 + i
                text = title
                isChecked = key == current
            })
        }
        group.setOnCheckedChangeListener { _, checked ->
            Sounds.CHOICES.getOrNull(checked - 1000)?.let { Prefs.setSound(this, it.first) }
        }

        val label = findViewById<TextView>(R.id.volumeLabel)
        val bar = findViewById<SeekBar>(R.id.volume)
        bar.progress = Prefs.volume(this)
        label.text = "Volume: ${bar.progress}%"
        bar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar, value: Int, fromUser: Boolean) {
                label.text = "Volume: $value%"
                if (fromUser) Prefs.setVolume(this@MainActivity, value)
            }
            override fun onStartTrackingTouch(seekBar: SeekBar) {}
            override fun onStopTrackingTouch(seekBar: SeekBar) {}
        })

        findViewById<Button>(R.id.preview).setOnClickListener {
            Sounds.preview(this, Prefs.sound(this), Sounds.gain(Prefs.volume(this)))
        }
    }

    private fun showLastReceived() {
        val lines = Prefs.history(this)
        val link = if (Prefs.code(this) == null) "" else "Direct link to website: ${Prefs.directStatus}\n"
        findViewById<TextView>(R.id.lastReceived).text = link +
            if (lines.isEmpty()) "No alerts received on this phone yet."
            else "Recent alerts (newest first):\n" + lines.joinToString("\n")
    }

    private fun setItem(id: Int, label: String, ok: Boolean) {
        findViewById<Button>(id).apply {
            text = if (ok) "✓ $label" else "Allow: $label"
            isEnabled = !ok
        }
    }

    @SuppressLint("BatteryLife") // sideloaded alarm app: asking directly is the point
    private fun requestBatteryExemption() {
        open(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }

    private fun open(intent: Intent) {
        try {
            startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
    }
}
