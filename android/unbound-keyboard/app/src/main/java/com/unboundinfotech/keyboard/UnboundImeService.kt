package com.unboundinfotech.keyboard

import android.content.Intent
import android.inputmethodservice.InputMethodService
import android.inputmethodservice.Keyboard
import android.inputmethodservice.KeyboardView
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.LinearLayout
import kotlin.concurrent.thread

/**
 * Unbound Keyboard — Grammarly-like coaching in the current field only.
 * Never sends password / PIN / visible-password boxes. Does not store the buffer.
 * Spelling runs on the phone. The house key is only for polish / word habits.
 */
class UnboundImeService : InputMethodService(), KeyboardView.OnKeyboardActionListener {
    private lateinit var keyboardView: KeyboardView
    private lateinit var qwerty: Keyboard
    private lateinit var numbers: Keyboard
    private lateinit var candidateRow: LinearLayout
    private val handler = Handler(Looper.getMainLooper())
    private var shifted = false
    private var symbols = false
    private var secretField = false
    private var lastProofread: ProofreadResult? = null
    private val ignored = mutableSetOf<String>()
    private val debounce = Runnable { proofreadField() }

    override fun onCreateInputView(): View {
        val root = layoutInflater.inflate(R.layout.ime, null)
        keyboardView = root.findViewById(R.id.keyboard)
        candidateRow = root.findViewById(R.id.candidate_row)
        qwerty = Keyboard(this, R.xml.qwerty)
        numbers = Keyboard(this, R.xml.numbers)
        keyboardView.keyboard = qwerty
        keyboardView.setOnKeyboardActionListener(this)
        return root
    }

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        secretField = PasswordGuard.isSecretField(info)
        if (!restarting) {
            ignored.clear()
            lastProofread = null
        }
        candidateRow.removeAllViews()
        if (secretField) {
            addChip("Password box — I won't read this")
        }
        symbols = false
        keyboardView.keyboard = qwerty
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
            Keyboard.KEYCODE_MODE_CHANGE -> {
                symbols = !symbols
                keyboardView.keyboard = if (symbols) numbers else qwerty
                keyboardView.isShifted = shifted
            }
            KEYCODE_GLOBE -> showInputMethodPicker()
            Keyboard.KEYCODE_DONE, 10 -> ic.performEditorAction(EditorInfo.IME_ACTION_DONE)
            32 -> {
                ic.commitText(" ", 1)
                scheduleProofread()
            }
            else -> {
                if (primaryCode < 0) return
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

    private fun showInputMethodPicker() {
        val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
        imm.showInputMethodPicker()
    }

    private fun scheduleProofread() {
        handler.removeCallbacks(debounce)
        if (secretField) return
        handler.postDelayed(debounce, 700)
    }

    private fun fieldText(): String {
        val ic = currentInputConnection ?: return ""
        val before = ic.getTextBeforeCursor(BEFORE_WINDOW, 0) ?: ""
        val after = ic.getTextAfterCursor(AFTER_WINDOW, 0) ?: ""
        return before.toString() + after.toString()
    }

    private fun housePair(): Pair<String, String> {
        val prefs = getSharedPreferences("unbound", MODE_PRIVATE)
        return (prefs.getString("house_url", "") ?: "") to (prefs.getString("house_key", "") ?: "")
    }

    private fun proofreadField() {
        if (secretField) return
        val text = fieldText()
        if (text.isBlank()) {
            handler.post { candidateRow.removeAllViews() }
            return
        }
        val local = LocalProofread.proofread(text)
        handler.post { showResult(local, unpairedHint = true) }
        val (url, key) = housePair()
        if (url.isBlank() || key.isBlank()) return
        thread {
            val result = try {
                WritingClient.proofread(url, key, text)
            } catch (_: Exception) {
                null
            } ?: return@thread
            handler.post { showResult(result, unpairedHint = false) }
        }
    }

    private fun showResult(result: ProofreadResult, unpairedHint: Boolean) {
        lastProofread = result
        candidateRow.removeAllViews()
        if (result.secret) {
            addChip(result.styleNote.ifBlank { "That looks private" })
            return
        }
        val shown = result.issues.filter { issueKey(it) !in ignored }.take(6)
        val autos = shown.any { it.auto || it.kind == "spelling" || it.kind == "grammar" }
        if (autos && result.corrected.isNotBlank() && result.corrected != fieldText()) {
            addChip("Fix spelling") { fixSpelling() }
        }
        if (shown.isNotEmpty()) {
            addChip("Leave it") { leaveIt(shown) }
        }
        if (shown.isEmpty()) {
            addChip(result.styleNote.ifBlank { "Looks clean" })
        } else {
            for (issue in shown) {
                val label = if (issue.suggestions.isNotEmpty()) {
                    "${issue.text} → ${issue.suggestions[0]}"
                } else {
                    issue.text
                }
                addChip(label) { applyIssue(issue) }
            }
        }
        val (url, key) = housePair()
        if (unpairedHint && (url.isBlank() || key.isBlank())) {
            addChip("Open Unbound Keyboard settings") { openSettings() }
        }
    }

    private fun issueKey(issue: WritingIssue): String {
        return "${issue.kind}:${issue.text.lowercase()}"
    }

    private fun fixSpelling() {
        val result = lastProofread ?: return
        val ic = currentInputConnection ?: return
        val before = (ic.getTextBeforeCursor(BEFORE_WINDOW, 0) ?: "").toString()
        val after = (ic.getTextAfterCursor(AFTER_WINDOW, 0) ?: "").toString()
        ic.deleteSurroundingText(before.length, after.length)
        ic.commitText(result.corrected, 1)
        lastProofread = null
        candidateRow.removeAllViews()
        addChip("Looks clean")
        scheduleProofread()
    }

    private fun leaveIt(shown: List<WritingIssue>) {
        for (issue in shown) ignored.add(issueKey(issue))
        candidateRow.removeAllViews()
        addChip("Okay — I won't nag about those.")
    }

    private fun applyIssue(issue: WritingIssue) {
        val replacement = issue.suggestions.firstOrNull() ?: return
        val ic = currentInputConnection ?: return
        val before = (ic.getTextBeforeCursor(BEFORE_WINDOW, 0) ?: "").toString()
        val after = (ic.getTextAfterCursor(AFTER_WINDOW, 0) ?: "").toString()
        val full = before + after
        if (issue.start < 0 || issue.end > full.length || issue.start > issue.end) return
        ic.deleteSurroundingText(before.length, after.length)
        ic.commitText(full.substring(0, issue.start) + replacement + full.substring(issue.end), 1)
        scheduleProofread()
    }

    private fun openSettings() {
        val intent = Intent(this, SettingsActivity::class.java)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
    }

    private fun addChip(label: String, onClick: (() -> Unit)? = null) {
        val btn = Button(this)
        btn.text = label
        btn.textSize = 12f
        btn.setOnClickListener { onClick?.invoke() }
        candidateRow.addView(btn)
    }

    companion object {
        const val KEYCODE_GLOBE = -10
        const val BEFORE_WINDOW = 4000
        const val AFTER_WINDOW = 400
    }
}
