# Password recovery

Choose **Forgot password?** beneath the password field on `/desk`, enter the account email, and choose **Send reset link**. The email opens `/reset-password`, where the user enters and confirms a new password. Success returns them to sign-in; previous browser sessions are revoked.

## Enable in production

1. For an existing Supabase deployment, run [supabase/password_reset.sql](../supabase/password_reset.sql) in the Supabase SQL Editor. New installations using `supabase/schema.sql` already include these changes. The migration adds reset digest/expiry/cooldown fields and a service-role-only database function for atomic password updates and session revocation. SQLite migrates automatically.
2. Keep the existing backend `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM` settings configured for outbound mail. The sender falls back to `SMTP_USER` if `SMTP_FROM` is empty.
3. Set backend `PASSWORD_RESET_URL=https://your-website.example/reset-password`. When omitted, the backend uses the origin of `DASHBOARD_URL` or `PAYSTACK_CALLBACK_URL`, with `/reset-password`. Local development falls back to `http://localhost:3000/reset-password`. Non-local links require HTTPS. The app never constructs reset links from untrusted request headers.
4. Redeploy the Python API and dashboard. Local development uses `cd dashboard && npm run dev`.

The UI reports recovery as unavailable when email settings or the required database fields are missing. This feature uses the application's existing custom accounts; Supabase Auth's separate password-recovery settings do not change these passwords.

## Behavior and verification

- Requests return the same confirmation for registered and unknown emails. Account lookup and email delivery run after the response. No reset token is returned by the API.
- Links contain a cryptographically random 256-bit token. Only its SHA-256 digest is stored. Links expire after 30 minutes, work once, and are replaced when a newer link is issued. Requests are limited to one per account per minute.
- The token travels in the URL fragment, stays out of server request logs, and is removed from browser history on opening the form. The reset page sets a no-referrer policy.
- New passwords require 12–128 characters. The client checks confirmation. The server consumes the token, updates the password, and revokes existing sign-in sessions in one database transaction. Resetting does not automatically sign the user in.
- Tests use temporary SQLite storage and mocked/captured email. No real reset messages are sent by verification. Cloud adapter tests verify request contracts; the Supabase SQL migration must be applied separately.

Run recovery checks from the project root:

```bash
.venv/bin/python -m unittest tests.test_password_reset -q
```

These choices follow the [OWASP password recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
