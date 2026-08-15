package com.unboundinfotech.keyboard

import android.inputmethodservice.InputMethodService
import android.inputmethodservice.Keyboard
import android.inputmethodservice.KeyboardView
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.LinearLayout
import kotlin.concurrent.thread

/**
 * Unbound Keyboard — Grammarly-like coaching in the current field only.
 * Never sends password / PIN / visible-password boxes. Does not store the buffer.
 */
class UnboundImeService : InputMethodService(), KeyboardView.OnKeyboardActionListener {
    private lateinit var keyboardView: KeyboardView
    private lateinit var qwerty: Keyboard
    private lateinit var candidateRow: LinearLayout
    private val handler = Handler(Looper.getMainLooper())
    private var shifted = false
    private var secretField = false
    private var lastProofread: ProofreadResult? = null
    private val debounce = Runnable { proofreadField() }

    override fun onCreateInputView(): View {
        val root = layoutInflater.inflate(R.layout.ime, null)
        keyboardView = root.findViewById(R.id.keyboard)
        candidateRow = root.findViewById(R.id.candidate_row)
        qwerty = Keyboard(this, R.xml.qwerty)
        keyboardView.keyboard = qwerty
        keyboardView.setOnKeyboardActionListener(this)
        return root
    }

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        secretField = PasswordGuard.isSecretField(info)
        candidateRow.removeAllViews()
        if (secretField) {
            addChip("Password box — I won't read this")
        }
    }

    override fun onPress(primaryCode: Int) {}
    override fun onRelease(primaryCode: Int) {}
    override fun swipeLeft() {}
    override fun swipeRight() {}
    override fun swipeDown() {}
    override fun swipeUp() {}

    override fun onText(text: CharSequence?) {
        currentInputConnection?.commitText(text, 1)
        scheduleProofread()
    }

    override fun onKey(primaryCode: Int, keyCodes: IntArray?) {
        val ic = currentInputConnection ?: return
        when (primaryCode) {
            Keyboard.KEYCODE_DELETE -> {
                ic.deleteSurroundingText(1, 0)
                scheduleProofread()
            }
            Keyboard.KEYCODE_SHIFT -> {
                shifted = !shifted
                keyboardView.isShifted = shifted
            }
            Keyboard.KEYCODE_DONE, 10 -> ic.performEditorAction(EditorInfo.IME_ACTION_DONE)
            32 -> {
                ic.commitText(" ", 1)
                scheduleProofread()
            }
            else -> {
                var ch = primaryCode.toChar()
                if (shifted && ch.isLetter()) ch = ch.uppercaseChar()
                ic.commitText(ch.toString(), 1)
                if (shifted && ch.isLetter()) {
                    shifted = false
                    keyboardView.isShifted = false
                }
                scheduleProofread()
            }
        }
    }

    private fun scheduleProofread() {
        handler.removeCallbacks(debounce)
        if (secretField) return
        handler.postDelayed(debounce, 700)
    }

    private fun fieldText(): String {
        val ic = currentInputConnection ?: return ""
        val before = ic.getTextBeforeCursor(500, 0) ?: ""
        val after = ic.getTextAfterCursor(120, 0) ?: ""
        return before.toString() + after.toString()
    }

    private fun proofreadField() {
        if (secretField) return
        val text = fieldText()
        if (text.isBlank()) return
        val prefs = getSharedPreferences("unbound", MODE_PRIVATE)
        val url = prefs.getString("house_url", "") ?: ""
        val key = prefs.getString("house_key", "") ?: ""
        if (url.isBlank() || key.isBlank()) {
            handler.post {
                candidateRow.removeAllViews()
                addChip("Open Unbound Keyboard settings")
            }
            return
        }
        thread {
            val result = try {
                WritingClient.proofread(url, key, text)
            } catch (_: Exception) {
                null
            } ?: return@thread
            handler.post { showResult(result) }
        }
    }

    private fun showResult(result: ProofreadResult) {
        lastProofread = result
        candidateRow.removeAllViews()
        if (result.secret) {
            addChip(result.styleNote.ifBlank { "That looks private" })
            return
        }
        val shown = result.issues.take(6)
        if (shown.isEmpty()) {
            addChip(result.styleNote.ifBlank { "Looks clean" })
            return
        }
        for (issue in shown) {
            val label = if (issue.suggestions.isNotEmpty()) {
                "${issue.text} → ${issue.suggestions[0]}"
            } else {
                issue.text
            }
            addChip(label) { applyIssue(issue) }
        }
    }

    private fun applyIssue(issue: WritingIssue) {
        val replacement = issue.suggestions.firstOrNull() ?: return
        val ic = currentInputConnection ?: return
        val before = (ic.getTextBeforeCursor(500, 0) ?: "").toString()
        val after = (ic.getTextAfterCursor(120, 0) ?: "").toString()
        val full = before + after
        if (issue.start < 0 || issue.end > full.length || issue.start > issue.end) return
        ic.deleteSurroundingText(before.length, after.length)
        ic.commitText(full.substring(0, issue.start) + replacement + full.substring(issue.end), 1)
        scheduleProofread()
    }

    private fun addChip(label: String, onClick: (() -> Unit)? = null) {
        val btn = Button(this)
        btn.text = label
        btn.textSize = 12f
        btn.setOnClickListener { onClick?.invoke() }
        candidateRow.addView(btn)
    }
}
