---
name: heirloom-winui
description: >-
  Builds and analyzes the native WinUI 3 Heirloom studio (Assist, Twin, mixer,
  vault, publish). Use when editing desktop/Heirloom, AssistantViewModel,
  PcToolkit, TwinViewModel, dock/menus, or when the user mentions Assist, Twin
  sitting, WASAPI mixer, or Heirloom-ready.
---

# Heirloom WinUI studio

Owner product is `desktop/Heirloom/`. Not the React app. Not PySide6.

## Before changing UI or copy

Read UnboundCursor keep/reject: `GET http://127.0.0.1:7733/library` or `F:/UnboundCursor/data/knowledge/library.json`. Do not ship `against` tropes.

## Product split

| Surface | Files | Voice |
|---|---|---|
| Assist | `ViewModels/AssistantViewModel.cs`, `Services/PcToolkit.cs` | Copilot. Not the owner. |
| Twin | `ViewModels/TwinViewModel.cs` | First person, vault-grounded. |

Dock: Sit = Assist, Today, Mixer. Twin group = Sitting, Portrait, Abilities, Skills, Avatar.

Cloud chat: `backend/routers/desktop.py` `ChatReq.mode`; `backend/twin_runtime.py` `role=`. Twin strips `pc_control` / `screen_vision` / `terminal`.

Tool catalog: [tools.md](tools.md).

## Do not

- Launch `Heirloom.exe`, `dotnet run` on the WinUI project, Explorer, MessageBox, or UAC unless the owner asked to run it.
- Kill a running Heirloom process.
- Drive vendor DOM / captchas.
- Give Twin PC control. Heirs inherit Twin, not the copilot.

## Verify

```text
dotnet build desktop/Heirloom/Heirloom.csproj -c Release -r win-x64
dotnet publish desktop/Heirloom/Heirloom.csproj -c Release -r win-x64 --self-contained true -o desktop/dist/Heirloom-ready /p:WindowsPackageType=None /p:PublishTrimmed=false
```

Tell the owner to quit the old process and start `desktop/dist/Heirloom-ready/Heirloom.exe`.
