# Mail setup: himalaya with Gmail

himalaya is OpenClaw's bundled mail skill (v2 config format shown here). Any IMAP/SMTP provider works; Gmail needs an app password (2-step verification on). On Linux replace the Keychain commands with `secret-tool` or `pass`.

## Store the app password (macOS Keychain)
Store the 16-character app password in the Keychain once:
```bash
security add-generic-password -a "deine.adresse@gmail.com" -s himalaya-gmail -w
```
Then `~/.config/himalaya/config.toml`:
```toml
[accounts.gmail]
email = "deine.adresse@gmail.com"
display-name = "Vorname Nachname"
default = true

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "deine.adresse@gmail.com"
backend.auth.type = "password"
backend.auth.cmd = "security find-generic-password -a deine.adresse@gmail.com -s himalaya-gmail -w"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 465
message.send.backend.encryption.type = "tls"
message.send.backend.login = "deine.adresse@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "security find-generic-password -a deine.adresse@gmail.com -s himalaya-gmail -w"
```
Check: `himalaya account check` then `himalaya envelope list`.

