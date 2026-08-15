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
        val url = findViewById<EditText>(R.id.house_url)
        val key = findViewById<EditText>(R.id.house_key)
        url.setText(prefs.getString("house_url", ""))
        key.setText(prefs.getString("house_key", ""))
        findViewById<Button>(R.id.save).setOnClickListener {
            prefs.edit()
                .putString("house_url", url.text.toString().trim())
                .putString("house_key", key.text.toString().trim())
                .apply()
            Toast.makeText(this, "Saved. Choose Unbound Keyboard when you type.", Toast.LENGTH_LONG).show()
        }
    }
}
