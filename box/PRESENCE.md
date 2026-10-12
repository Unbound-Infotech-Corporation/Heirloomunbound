# Presence

Presence watches the lab room with one or more USB webcams and greets people the owner has taught. It is off unless this machine was installed with `--presence`. Product builds do not set `HEIRLOOM_PRESENCE`.

The room is fingerprint-locked, so people who were never taught are rare. An unknown face is never enrolled. The box stores face embeddings and one thumbnail per taught person. It does not store raw video.

## Models and license

InsightFace pretrained weights, including the packages the library downloads for you, are for non-commercial research. Presence does not download or load them. The InsightFace code license is MIT; the trained models are not.

Presence uses the OpenCV Zoo copies of two small models:

| Role | File | License | Source |
|---|---|---|---|
| Detector | `face_detection_yunet_2023mar.onnx` | MIT (Copyright 2020 Shiqi Yu) | [opencv_zoo YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| Recognizer | `face_recognition_sface_2021dec.onnx` | Apache-2.0 | [opencv_zoo SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface) |

The installer saves each `LICENSE` file next to the weights under `/var/lib/heirloom/presence/models/`. YuNet's MIT notice has to stay with the file. The 2023-03 YuNet export is the one OpenCV 4.x on Ubuntu 24.04 can run. The newer dynamic export is for OpenCV 5.

OpenCV itself is Apache-2.0 (`python3-opencv`).

SFace cosine similarity uses `0.36` as the default, the same cutoff the OpenCV sample uses. The owner can change it on `/presence`. A score under the threshold is an unknown face. It is logged, not saved as a person.

## GPU

The reference box is an RTX 3090 (24 GB) with 32 GB of RAM, often with Observer's chat and vision models resident (about 19 GB; see [OBSERVER.md](OBSERVER.md)). YuNet is a few hundred kilobytes and SFace is about 40 MB. Presence does not unload Ollama and does not change the chat model.

| Knob | Default | Meaning |
|---|---|---|
| `PRESENCE_VRAM_BUDGET_MIB` | `512` | Free VRAM required before CUDA. |
| Free memory unknown | CPU | `nvidia-smi` not answering, so Presence does not guess. |
| Free memory under the budget | CPU | Ollama keeps the card. |
| CUDA init fails | CPU | The daemon retries the CPU backend. |

Recognition runs after a motion gate, at 2–5 frames per second (`PRESENCE_FPS`, default 3, clamped into that range). A calm picture does not run the networks. A calm picture also does not mark someone as gone: if the frame has not changed, people who were already here stay here. Walking out moves the picture, recognition no longer sees them, and a departure is recorded after `depart_seconds` (default 30). If every camera is unplugged, presence freezes instead of departing everyone.

## Cameras

UVC webcams show up as `/dev/video*`. The daemon re-scans `/sys/class/video4linux` every loop and drops a camera that stops answering so the next loop can open it again. `box/presence/99-heirloom-presence.rules` asks systemd to start `heirloom-presence.service` when a video4linux device is added. The unit uses `Restart=on-failure`.

HDMI capture cards belong to Observer. Presence skips names containing `xr1`, `evga`, `elgato`, `4k60`, `cam link`, or `hdmi`, and it skips the device Observer currently has open. Set `PRESENCE_DEVICES=/dev/video2,/dev/video3` to pin the list.

Several cameras are one room. A person seen on any of them is present. The systemd unit allows `/dev/video0` through `/dev/video5`. A sixth webcam needs another `DeviceAllow` line.

## Teaching

`/presence` is owner-only.

- **Teach a person** asks for a name, a relationship, a greeting, and a checkbox that the person agreed.
- Capture several live samples (about five), or upload JPEGs. The camera service turns each picture into an embedding and a small thumbnail, then deletes the picture. Uploads that the service never takes are deleted after 15 minutes.
- Edit the name, relationship, or greeting. Delete removes that person's directory, including embeddings and the thumbnail.
- **Forget everyone** deletes every person, every embedding, every thumbnail, and every unknown review image.
- **Test recognition** looks once and does not save a new person. Use it while you move the threshold.

The owner's relationship should be `owner`. Assignments that ask to wait until the owner is in the room use that relationship.

Without the consent checkbox the person is not created.

## Events

Arrivals and departures are appended under `/var/lib/heirloom/presence/events.jsonl`. A greeting is spoken only when the last greeting for that person was at least `PRESENCE_DEBOUNCE_MINUTES` ago (default 10). Coming back sooner still records the arrival and does not greet again.

`GET /api/presence/now` tells the Twin who is in the room. The owner Twin can say welcome back from that list. Heirs do not receive the list.

An assignment or clone report can wait for the owner. Set `deliver_when` to `owner_present`, or write the goal so it says the report should wait until the owner is in the room (for example "until the owner is present"). The draft stays on the assignment. It is marked done when a person whose relationship is `owner` is present. Presence off does not hold anything.

## Unknown faces

An unrecognized face writes one event: a timestamp and the kind `unrecognized`. No embedding and no name. The same face does not write another line until the unknown debounce window passes (default 10 minutes).

`PRESENCE_UNKNOWN_THUMBNAILS=0`. Turn it on from `/presence` if you want one JPEG kept for review. Those files are deleted after 24 hours. The fingerprint lock is why this stays off: strangers should not be in the room.

## Observer

When both features are on, a note can carry a short cue: `at desk while <screen> is on screen`, or `away`. That is a label on the observation, not a second video. Pause stops both.

## Pause

One switch covers Observer and Presence:

- `heirloom-box presence pause` and `heirloom-box presence resume`
- `heirloom-box observer pause` and `heirloom-box observer resume`
- Pause / Resume on `/presence` and `/observer`

Quiet hours pause only inside the window. `PRESENCE_QUIET_HOURS=23:00-07:00` is the presence schedule. If that is empty, Presence uses `OBSERVER_QUIET_HOURS`. Quiet hours do not latch.

## Privacy

Everything stays on the box. There is no cloud face API. Heirs and callers receive 404 from `/api/presence`. The heir Twin prompt does not include who is in the room.

Biometric data here is the embedding plus the thumbnail. **Forget everyone** removes it in one action. Deleting one person removes only that person.

### Consent, for the product later

Illinois BIPA, Texas CUBI, Washington's biometric statute, and similar laws treat a face embedding as a biometric identifier. A commercial product that does this needs, before collection:

- written notice of what is collected, why, and how long it is kept
- a written release from each person
- a public retention schedule and destruction when the purpose ends
- no sale of the biometric data, and no disclosure except as the statute allows

This lab path is the owner's machine, a consent checkbox, local storage, and a delete action. It is not a BIPA notice or a release. Do not ship Presence to other households by turning the flag on in a product build.

## Status

`heirloom-box status` includes a presence section: enabled, cameras, fps, enrolled, who is present, paused, model, backend. `GET /api/health` includes the same facts under `presence`, without embeddings.

```bash
heirloom-box presence status
heirloom-box presence pause
heirloom-box presence resume
heirloom-box presence forget
```

Spoken greetings use the local Chatterbox service when `PRESENCE_SPEAK=1` (the installer sets that if you also passed `--with-chatterbox`). The URL is `PRESENCE_SPEAK_URL` (`http://127.0.0.1:8010/speak`). If speak is off, the greeting is still an event and the Twin can say it. Audio does not leave the box.

## Install

```bash
sudo bash box/install.sh --presence
```

That installs `python3-opencv`, `v4l-utils`, and `ffmpeg`, downloads the two models and their license files, writes `/etc/heirloom/presence.enabled`, and enables `heirloom-presence.service`. A later `sudo bash box/install.sh` without the flag keeps Presence on while that marker file exists. A dry-run does not create the marker and does not download the models.

`--dry-run --presence` prints the plan and does not install packages, write the marker, or start the service.
