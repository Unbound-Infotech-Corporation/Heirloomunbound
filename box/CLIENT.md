# Using Heirloom from your Windows PC

The Twin Box is the computer that watches, listens, and answers as your Twin. Your Windows PC (the one you sit at) can be a window onto that box. A small companion icon in the taskbar shows whether the box is there.

You do not need to type commands for everyday use. The steps below are the ones that matter.

## First choice in Heirloom

Open Heirloom on the Windows PC. The first screen asks where Heirloom should run.

- **Run Heirloom on this PC** downloads what this computer needs and keeps the Twin here.
- **Connect to my Twin Box** uses the box for Twin chat, clones, assignments, approvals, presence, and the observer. This PC does not download those models.

Assist still runs on the Windows PC. That is the helper that can open programs and look at this computer. The Twin on the box does not get those tools.

Room VR stays off until you turn it on in Settings. Connecting to the box does not put you in a headset.

## The box address

The usual address is `https://192.168.0.111`. If the installer printed a different address, use that. It starts with `https://`.

## Trusting the certificate

The box uses its own certificate so the connection stays private on your home network. Windows does not know that certificate yet.

1. Choose **Show the certificate**.
2. Read the fingerprint on the screen.
3. If it is your box, choose **This is my box**.

Heirloom remembers that fingerprint. Later connections are checked against it. Other sites are not affected. You are not turning certificate checks off.

## Signing in

On the box, someone with access to that computer runs this once:

`sudo heirloom-box set-owner you@example.com`

It asks for a password and does not print the password back.

On the Windows PC, type the same email and password and choose **Connect**. Heirloom stores the sign-in on this Windows user with Windows data protection. It does not store the password.

## The taskbar companion

The companion is a separate small program, Heirloom Companion. Its icon means:

- **Green** — the box answered, and the observer has a picture coming in.
- **Amber** — the box answered, but the observer is paused or has no picture.
- **Red** — the box did not answer.

Hover the icon for the address, how long the answer took, the observer (frames per second and notes today), who presence sees, the cameras, and the graphics card or model when the box reports them.

The menu can pause or resume the observer. That needs you to be signed in. **Open Twin** opens Heirloom on this PC, or the box page in the browser if Heirloom is not beside the companion. **Settings** is where you set the address, pin the certificate, sign in, and choose two options:

- Start the companion when you sign in to Windows. This is off until you turn it on.
- A short notice when the box drops offline or comes back. You can turn that off.

The companion never restarts the box, and it never restarts Windows.

## If the address or the disk changes

The box keeps its files in `/var/lib/heirloom` unless the person who installed it chose another folder. That folder is the only place you would name if you ever reinstall.

Samsung 970 drives on some boxes drop off the bus. The installer can add a power fix for that with `--nvme-power-fix`. It saves a copy of the boot settings first. It does not reboot the box by itself. A person still has to restart the box later for that fix to apply.

## What stays on the Windows PC

Assist, the volume mixer for Heirloom, and anything you do with this PC's files stay here. The box is the Twin, the observer, and presence. Those are separate on purpose.
