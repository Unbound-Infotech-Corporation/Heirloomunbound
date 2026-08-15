package com.unboundinfotech.keyboard

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

data class WritingIssue(
    val start: Int,
    val end: Int,
    val kind: String,
    val text: String,
    val suggestions: List<String>,
    val note: String,
    val auto: Boolean = false,
)

data class ProofreadResult(
    val secret: Boolean,
    val corrected: String,
    val styleNote: String,
    val issues: List<WritingIssue>,
)

object WritingClient {
    fun proofread(houseUrl: String, houseKey: String, text: String): ProofreadResult {
        val parsed = HouseKey.parse("$houseUrl\n$houseKey")
        val base = (parsed.first.ifBlank { houseUrl }).trim().trimEnd('/')
        val key = parsed.second.ifBlank { houseKey.trim() }
        val url = URL("$base/api/writing/proofread")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 8000
            readTimeout = 8000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Authorization", "Bearer $key")
        }
        OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(JSONObject().put("text", text).toString()) }
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val body = BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }
        conn.disconnect()
        if (code !in 200..299) {
            throw java.io.IOException("house HTTP $code")
        }
        val json = JSONObject(body)
        val issues = mutableListOf<WritingIssue>()
        val arr = json.optJSONArray("issues")
        if (arr != null) {
            for (i in 0 until arr.length()) {
                val item = arr.getJSONObject(i)
                val suggestions = mutableListOf<String>()
                val sug = item.optJSONArray("suggestions")
                if (sug != null) {
                    for (j in 0 until sug.length()) suggestions.add(sug.optString(j))
                }
                issues.add(
                    WritingIssue(
                        start = item.optInt("start"),
                        end = item.optInt("end"),
                        kind = item.optString("kind"),
                        text = item.optString("text"),
                        suggestions = suggestions,
                        note = item.optString("note"),
                        auto = item.optBoolean("auto"),
                    ),
                )
            }
        }
        return ProofreadResult(
            secret = json.optBoolean("secret"),
            corrected = json.optString("corrected", text),
            styleNote = json.optString("style_note"),
            issues = issues,
        )
    }
}
