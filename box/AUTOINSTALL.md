# Heirloom Twin Box USB install

This builds one USB stick that installs Ubuntu Server 24.04 and Heirloom with no questions. You set the internal disk serial first. The stick erases only that disk, and only after the live machine shows the same serial.

**Boot this stick only on the Twin Box.** On any other PC it can erase that PC's disk if the serial happens to match, or it stops if the serial does not match. Either way, do not boot it anywhere else.

The build script writes an `.iso` file. It does not write a USB disk. You flash that file yourself with Rufus or balenaEtcher.

## Turn Secure Boot off

Do this on the Twin Box before you boot the stick.

1. Restart the PC and open the firmware setup (often Del, F2, or F10 while it powers on).
2. Find Secure Boot and turn it **off**.
3. Save and exit.

The NVIDIA driver for the RTX 3090 uses open kernel modules. Ubuntu cannot finish the blue "enroll this key" screen by itself. Someone would have to stand at the keyboard and confirm the key. This install does not try that. If Secure Boot is still on, first boot stops, writes the reason to the log, and does not install the driver or Heirloom.

## Find the disk serial

On the Twin Box, from Ubuntu or a live session, before you replace the system:

```bash
lsblk -d -o NAME,MODEL,SIZE,SERIAL,TRAN,RM
```

Use the SERIAL of the internal system disk. `RM` is `0`. `TRAN` is `sata` or `nvme`. Skip anything with `TRAN` of `usb` and skip the USB stick you booted from.

From Windows, open PowerShell as Administrator:

```powershell
Get-Disk | Select-Object Number,FriendlyName,SerialNumber,BusType
```

Use `SerialNumber` for the internal disk (`BusType` is SATA or NVMe, not USB).

## Fill in the config

From a checkout of this repo:

```bash
cp box/autoinstall/config.env.example box/autoinstall/config.env
```

Edit `box/autoinstall/config.env`:

| Setting | What to put |
|---|---|
| `TARGET_DISK_SERIAL` | The serial from the step above. Required. The build refuses to run if this is empty. |
| `INITIAL_PASSWORD` | A password for the `heirloom` account. Or leave it empty and put an SSH public key in `box/autoinstall/authorized_keys` (one key per line). |
| `SSH_PASSWORD_AUTH` | `yes` allows SSH with the password. `no` allows keys only, and then a key is required. |
| `HEIRLOOM_REPO_URL` | Git URL first boot clones. Or put a tarball at `box/autoinstall/payload/heirloom.tar.gz` that contains `box/install.sh`. One of the two is required. |
| `TAILSCALE_AUTH_KEY` | Optional. When set, the box joins your tailnet by itself. The key is stored on the USB. Keep the stick private. |
| `NVIDIA_DRIVER_BRANCH` | Leave `latest`. That is the current production driver from NVIDIA's CUDA repository. A number such as `580` pins that branch. |
| `NVIDIA_KERNEL_MODULES` | Leave `open`. That is the right module set for the RTX 3090. |
| `EXPECTED_GPU_NAME` | Leave `3090`. First boot will not install Heirloom until `nvidia-smi` prints that text. |

`config.env` is not committed. `INITIAL_PASSWORD` is hashed and is not copied onto the ISO. A Tailscale key, if you set one, is copied onto the ISO.

## Build the ISO

On Linux:

```bash
bash box/autoinstall/build-usb.sh
```

The script downloads Ubuntu Server 24.04.5 if you do not already have it, checks the SHA256, and writes:

`box/autoinstall/out/heirloom-twinbox-autoinstall.iso`

On Windows, from the repo in PowerShell (WSL must be installed):

```powershell
powershell -ExecutionPolicy Bypass -File box\autoinstall\build-usb.ps1
```

Neither script flashes a USB device. A path under `/dev/` or a `\\.\` physical drive is refused.

## Flash the stick

Use one of these:

- **Rufus:** select the ISO, choose **DD Image mode** (not ISO mode). ISO mode can drop the autoinstall files and the stick will stop and ask questions.
- **balenaEtcher:** select the ISO and the USB stick.

Eject the stick. Boot it only on the Twin Box.

## What the first boot does

The installer copies Ubuntu onto the one matching internal disk, reboots, then a service continues by itself. You do not answer prompts.

1. Full Ubuntu upgrade, the HWE kernel, and current firmware.
2. Reboot into that kernel.
3. Install the latest production NVIDIA driver (`nvidia-open` from the CUDA apt repo), the CUDA toolkit, cuDNN, `nvtop`, and the NVIDIA container toolkit. Docker is configured for the NVIDIA runtime once Docker is up.
4. Reboot so the driver loads.
5. Run `nvidia-smi`. The output must include `3090`. The result is written to the log. If the card is missing or is a different GPU, the service stops and Heirloom is not installed.
6. Join Tailscale if you set a key.
7. Clone or unpack Heirloom and run `box/install.sh --unattended --dev-tools --observer --presence`.
8. Run `heirloom-box status`, then turn the first-boot service off so it does not run again.

Progress is in `/var/log/heirloom-firstboot.log`. The disk check from the installer is in `/var/log/heirloom-resolve-disk.log`.

## Log in

The account is `heirloom` on host `heirloom-twinbox`. Use the password or the SSH key you configured.

```bash
heirloom-box status
```

## Update the NVIDIA stack later

On the box, after it is installed:

```bash
sudo heirloom-box update-drivers
```

That upgrades the same CUDA-repo driver, toolkit, cuDNN, nvtop, and container toolkit. Reboot if it says the driver needs a reboot, then run `nvidia-smi`.

## When something stops

| What you see | What it means |
|---|---|
| The installer stops and the disk is unchanged | The serial was empty, matched nothing, matched more than one disk, or matched a USB stick. Nothing was erased. Fix `TARGET_DISK_SERIAL`, rebuild, and flash again. |
| First boot stops and the log says Secure Boot is enabled | Turn Secure Boot off in firmware and reboot. The driver was not installed. |
| The log says `nvidia-smi` failed or the GPU does not match `3090` | The driver did not see the RTX 3090. Heirloom was not installed. The log line is the `nvidia-smi` output. |
| The service tries again after a network failure | It waits for the network and retries. A hard failure (Secure Boot, or the GPU check) does not retry in a loop. |
