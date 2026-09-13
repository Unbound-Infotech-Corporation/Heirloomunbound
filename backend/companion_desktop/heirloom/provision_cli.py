"""Headless provisioner for Heirloom Unbound Setup.

The Inno Setup bootstrap installs app bits, then runs this so downloads
resume, engine failures coach instead of aborting, and dedicated writes
install_profile. Safe without Qt.

    python -m heirloom.provision_cli --profile medium
    python -m heirloom.provision_cli --profile dedicated --vault D:\\HeirloomVault --consent
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import config
from .space_profiles import normalize_profile_id, provision_features, provision_manifest, recommend_profile, space_profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heirloom.provision_cli", description="Heirloom Unbound provisioner")
    parser.add_argument("--profile", default="", help="small | medium | large | dedicated (aliases: lite, full, max)")
    parser.add_argument("--recommend-gb", type=float, default=None, help="If set, print recommended profile for this free space and exit")
    parser.add_argument("--vault", default="", help="Vault / data drive (dedicated)")
    parser.add_argument("--consent", action="store_true", help="This PC exists for Heirloom Unbound")
    parser.add_argument("--start-with-windows", action="store_true", default=False)
    parser.add_argument("--power-plan", action="store_true", default=False, help="Consent to high-performance power plan")
    parser.add_argument("--branding", action="store_true", default=False)
    parser.add_argument("--no-warm", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", help="Print the final probe as JSON")
    args = parser.parse_args(argv)

    if args.recommend_gb is not None:
        rec = recommend_profile(args.recommend_gb)
        print(rec)
        return 0

    profile_id = normalize_profile_id(args.profile or None)
    profile = space_profile(profile_id)
    manifest = provision_manifest(profile_id)
    print(f"Heirloom Unbound · {profile['label']}")
    print(f"install_profile={profile_id} whisper={manifest['whisper']} vault={manifest['vault_tier']}")
    for line in (
        "No Pinokio. Official MSI / Docker / pip / Ollama / Hugging Face only.",
        "Engine failure coaches and continues. Only a fatal app-bit failure aborts.",
    ):
        print(line)

    settings = config.load_settings()
    settings["space_profile"] = profile_id
    settings["install_profile"] = profile_id
    settings["disk_profile"] = profile_id
    if args.vault:
        settings["vault_folder"] = args.vault
        settings["vault_drive"] = args.vault
    config.save_settings(settings)

    if profile_id == "dedicated":
        from .dedicated import apply_machine_role

        if not args.consent:
            print("dedicated: missing --consent (This PC exists for Heirloom Unbound). Writing profile only.")
            from .dedicated import write_install_profile

            write_install_profile(settings, "dedicated")
            config.save_settings(settings)
        else:
            apply_machine_role(
                consent=True,
                vault_drive=args.vault,
                start_with_windows=args.start_with_windows or True,
                power_plan_consent=args.power_plan,
                warm_engines=not args.no_warm,
                live_listen=True,
                branding=args.branding,
                progress=print,
            )

    from .models import provision

    features = provision_features(profile_id)
    probe: dict[str, Any] = provision(features, progress=print, profile_id=profile_id)
    if profile_id == "dedicated" and not args.no_warm:
        from .dedicated import warm_engine_probes

        warm_engine_probes(progress=print)
    if args.json:
        print(json.dumps({k: probe.get(k) for k in ("whisper", "ollama", "voicebox", "qwen3_tts", "latentsync", "log") if k in probe}, indent=2))
    err = probe.get("error")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
