Unbound Keyboard
================

A real Android keyboard for Heirloom. It fixes spelling and little grammar
slips as you type, notices words you lean on, and still sounds like you.

This is not Grammarly. We never read password boxes. We do not keep other
people's documents. A house key is a Heirloom token — not a Google,
Microsoft, or phone password.

On Windows, Unbound Keyboard is a writing helper in the Heirloom app
(tray menu, or Ctrl+Shift+U). A phone keyboard can sit in every app;
Windows cannot do that without watching every key, so the PC helper only
sees what you type or paste there.

Install on a phone
------------------

1. On a computer with Android Studio, open this folder (`android/unbound-keyboard`).
2. Plug in the phone (or use an emulator). Run the app once — that installs Unbound Keyboard.
3. On the phone: Settings → System → Languages & input → On-screen keyboard → Manage keyboards → turn on **Unbound Keyboard**.
4. When you type, choose Unbound Keyboard (the keyboard picker key, or long-press the space bar on some phones).
5. Open Unbound Keyboard settings. Paste your house address (the Heirloom website) and the house key from Heirloom → Write → Copy my house key.

The keyboard will not send text from password, PIN, or card-number boxes.

Build
-----

    ./gradlew :app:installDebug

Android Studio can create the Gradle wrapper if `gradlew` is missing.
