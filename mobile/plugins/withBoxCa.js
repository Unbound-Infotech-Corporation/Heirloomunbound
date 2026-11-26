// Android ignores user-installed CAs by default. The Heirloom box signs its own certificate with a
// box CA the owner installs on the phone (docs/MOBILE.md), so trust user CAs for this app only.
// The pairing QR also pins the box key (react-native-ssl-public-key-pinning), so a stray user CA
// alone cannot impersonate the box. No cleartext traffic.
const fs = require('fs');
const path = require('path');
const { withAndroidManifest, withDangerousMod } = require('expo/config-plugins');

const XML = `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false">
    <trust-anchors>
      <certificates src="system" />
      <certificates src="user" />
    </trust-anchors>
  </base-config>
</network-security-config>
`;

module.exports = function withBoxCa(config) {
  config = withDangerousMod(config, ['android', async (cfg) => {
    const dir = path.join(cfg.modRequest.platformProjectRoot, 'app', 'src', 'main', 'res', 'xml');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'heirloom_network_security.xml'), XML);
    return cfg;
  }]);
  return withAndroidManifest(config, (cfg) => {
    const app = cfg.modResults.manifest.application[0];
    app.$['android:networkSecurityConfig'] = '@xml/heirloom_network_security';
    return cfg;
  });
};
