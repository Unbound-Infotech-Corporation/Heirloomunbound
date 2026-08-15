Unbound Keyboard
================

A real Android keyboard for Heirloom. It fixes spelling and little grammar
slips as you type, notices words you lean on, and still sounds like you.

This is not Grammarly. We never read password boxes. We do not keep other
people's documents. A house key is a Heirloom token — not a Google,
Microsoft, or phone password.

Spelling works on the phone even before you paste a house key. The house
key is only so Unbound Keyboard can polish wording in your voice.

On Windows, Unbound Keyboard is a writing helper in the Heirloom app
(tray menu, or Ctrl+Shift+U). A phone keyboard can sit in every app;
Windows cannot do that without watching every key, so the PC helper only
sees what you type or paste there.

On iPhone, Apple does not let us install this keyboard. Use Write inside
the Heirloom app instead.

Install on an Android phone
---------------------------

1. If you have `UnboundKeyboard.apk` (in this folder or the try-it zip),
   tap it on the phone. Allow install from this source if Android asks.
2. If there is no APK yet, on a computer run:

       ./gradlew :app:assembleDebug

   Then copy `app/build/outputs/apk/debug/app-debug.apk` to the phone
   and tap it. Android Studio can do the same with Run.
3. On the phone: Settings → System → Languages & input → On-screen keyboard
   → Manage keyboards → turn on **Unbound Keyboard**.
4. When you type, tap 🌐 on this keyboard to switch back to Gboard (or
   your old keyboard). 123 opens numbers and symbols.
5. Open Unbound Keyboard settings. Paste the whole house slip from
   Heirloom → Write → Copy my house key. One paste.

The keyboard will not send text from password, PIN, or card-number boxes.
Tap **Fix spelling** to apply the little fixes, or **Leave it** if you
meant what you typed.

Build
-----

    ./gradlew :app:assembleDebug
    ./gradlew :app:installDebug
