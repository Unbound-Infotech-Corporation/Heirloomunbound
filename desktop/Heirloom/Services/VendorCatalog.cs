namespace Heirloom.Services;

public sealed record CoachStep(
    string Id,
    string Kind,
    string Title,
    string Body,
    IReadOnlyList<string> Bullets,
    string Copy,
    string OpenUrl,
    bool AutoOpen,
    string Cta,
    string SkipCta,
    string Placeholder);

public sealed record VendorService(
    string Id,
    string Label,
    string Powers,
    string SignupUrl,
    string DashboardUrl,
    string SavePath,
    string VerifyService,
    string Placeholder,
    string EmailQuery,
    IReadOnlyList<CoachStep> Steps);

public static class VendorCatalog
{
    public static IReadOnlyList<VendorService> ServicesFor(string email)
    {
        var clean = (email ?? "").Trim().ToLowerInvariant();
        return
        [
            Build(
                "elevenlabs",
                "ElevenLabs",
                "Cloned voice so the twin sounds like you.",
                "https://elevenlabs.io/app/sign-up",
                "https://elevenlabs.io/app/settings/api-keys",
                "/voice-clone/api-key",
                "sk_…",
                clean),
            Build(
                "did",
                "D-ID",
                "Talking-head video of your face.",
                "https://studio.d-id.com/",
                "https://studio.d-id.com/account-settings",
                "/avatar/api-key",
                "email:secret",
                clean),
            Build(
                "fal",
                "fal.ai",
                "Optional Avatar Studio beautify only.",
                "https://fal.ai/login",
                "https://fal.ai/dashboard/keys",
                "/avatar-studio/api-key",
                "key_id:key_secret",
                clean),
        ];
    }

    public static (string Label, string Url) InboxFor(string email)
    {
        var domain = email.Contains('@') ? email[(email.IndexOf('@') + 1)..] : "";
        return domain switch
        {
            "gmail.com" or "googlemail.com" => ("Gmail", "https://mail.google.com/mail/u/0/#inbox"),
            "outlook.com" or "hotmail.com" or "live.com" or "msn.com" => ("Outlook", "https://outlook.live.com/mail/0/"),
            "yahoo.com" or "ymail.com" => ("Yahoo Mail", "https://mail.yahoo.com/"),
            "icloud.com" or "me.com" or "mac.com" => ("iCloud Mail", "https://www.icloud.com/mail"),
            "proton.me" or "protonmail.com" => ("Proton Mail", "https://mail.proton.me/u/0/inbox"),
            _ => ("your email inbox", ""),
        };
    }

    private static VendorService Build(
        string id,
        string label,
        string powers,
        string signup,
        string dashboard,
        string savePath,
        string placeholder,
        string email)
    {
        var inbox = InboxFor(email);
        var signupUrl = string.IsNullOrWhiteSpace(email) ? signup : signup + (signup.Contains('?') ? "&" : "?") + "email=" + Uri.EscapeDataString(email);
        CoachStep[] steps =
        [
            new(
                "create_account",
                "pause",
                $"Create your {label} account",
                "Their official sign-up page is open. Click Create account, paste your email if the box is empty, then click I'm not a robot. Heirloom cannot press those.",
                [
                    "Click Create account / Sign up — Heirloom cannot press that for you.",
                    "If the email box is empty, paste (Ctrl+V). Heirloom copied it.",
                    "Click I'm not a robot, then submit their form.",
                ],
                email,
                signupUrl,
                true,
                "I signed up (and clicked I'm not a robot)",
                "",
                ""),
            new(
                "verify_email",
                "pause",
                $"Verify in {inbox.Label}",
                string.IsNullOrWhiteSpace(inbox.Url)
                    ? $"Open the inbox for {(string.IsNullOrWhiteSpace(email) ? "your email" : email)} and click the verify link from {label}."
                    : $"We opened {inbox.Label}. Find the message from {label} and click Verify.",
                [
                    string.IsNullOrWhiteSpace(email) ? "Use the same email you just typed." : $"Look for mail to {email}.",
                    "Open their message and click Verify / Confirm.",
                ],
                "",
                inbox.Url,
                inbox.Url.Length > 0,
                "I verified the email",
                "Skip — already verified",
                ""),
            new(
                "find_key",
                "pause",
                $"Get the {label} API key",
                "Open their API keys page and copy a key.",
                ["Copy the secret, then continue."],
                "",
                dashboard,
                true,
                "I'm on the API keys page",
                "",
                ""),
            new(
                "paste_key",
                "paste",
                "Paste the key into Heirloom",
                "This box stays in Heirloom. After it saves, the guide moves to the next vendor.",
                ["Paste the secret you copied. We never read keys off a screenshot."],
                "",
                "",
                false,
                "Verify & save",
                "",
                placeholder),
        ];
        return new VendorService(id, label, powers, signupUrl, dashboard, savePath, id, placeholder, "email", steps);
    }
}
