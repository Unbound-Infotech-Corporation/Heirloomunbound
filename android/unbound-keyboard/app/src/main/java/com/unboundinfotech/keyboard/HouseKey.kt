package com.unboundinfotech.keyboard

/**
 * One-paste house slip: URL + kb_ token. Not a Google / Microsoft / phone password.
 */
object HouseKey {
    private val KEY = Regex("kb_[A-Za-z0-9_-]+")
    private val URL = Regex("https?://[^\\s]+", RegexOption.IGNORE_CASE)

    fun parse(blob: String): Pair<String, String> {
        val text = blob.trim()
        val token = KEY.find(text)?.value ?: ""
        val rawUrl = URL.find(text)?.value ?: ""
        val url = rawUrl.trimEnd('/', '.', ',', ')')
        return url to token
    }

    fun format(houseUrl: String, token: String): String {
        val url = houseUrl.trim().trimEnd('/')
        val key = token.trim()
        val lines = mutableListOf("HOUSE")
        if (url.isNotEmpty()) lines.add(url)
        if (key.isNotEmpty()) lines.add(key)
        return lines.joinToString("\n") + "\n"
    }
}
