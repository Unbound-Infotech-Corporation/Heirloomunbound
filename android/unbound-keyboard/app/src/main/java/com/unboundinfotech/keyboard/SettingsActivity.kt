package com.unboundinfotech.keyboard

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class SettingsActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        val prefs = getSharedPreferences("unbound", MODE_PRIVATE)
        val blobField = findViewById<EditText>(R.id.house_blob)
        val savedUrl = prefs.getString("house_url", "") ?: ""
        val savedKey = prefs.getString("house_key", "") ?: ""
        blobField.setText(
            if (savedUrl.isNotBlank() || savedKey.isNotBlank()) {
                HouseKey.format(savedUrl, savedKey).trim()
            } else {
                ""
            },
        )
        findViewById<Button>(R.id.save).setOnClickListener {
            val pasted = blobField.text.toString()
            val (url, key) = HouseKey.parse(pasted)
            val nextUrl = url.ifBlank { savedUrl }
            val nextKey = key.ifBlank { savedKey }
            prefs.edit()
                .putString("house_url", nextUrl.trim())
                .putString("house_key", nextKey.trim())
                .apply()
            if (nextUrl.isBlank() || nextKey.isBlank()) {
                Toast.makeText(
                    this,
                    "Paste the whole house slip from Heirloom → Write. Spelling still works without it.",
                    Toast.LENGTH_LONG,
                ).show()
            } else {
                Toast.makeText(this, "Saved. Choose Unbound Keyboard when you type.", Toast.LENGTH_LONG).show()
            }
        }
    }
}
