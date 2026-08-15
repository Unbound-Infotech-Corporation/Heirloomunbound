package com.unboundinfotech.keyboard

import android.text.InputType
import android.view.inputmethod.EditorInfo

/** Skip coaching (and never send) password / PIN / visible-password fields. */
object PasswordGuard {
    fun isSecretField(info: EditorInfo?): Boolean {
        if (info == null) return false
        val cls = info.inputType and InputType.TYPE_MASK_CLASS
        val variation = info.inputType and InputType.TYPE_MASK_VARIATION
        if (cls == InputType.TYPE_CLASS_TEXT) {
            return variation == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
                variation == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD ||
                variation == InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        }
        if (cls == InputType.TYPE_CLASS_NUMBER) {
            return variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }
        return false
    }
}
