# Password recovery

Choose **Forgot password?** beneath the password field on `/desk`, enter the account email, and choose **Send reset link**. The email opens `/reset-password`, where the user enters and confirms a new password. Success returns them to sign-in; previous browser sessions are revoked.

## Enable in production

1. For an existing Supabase deployment, run [supabase/password_reset.sql](../supabase/password_reset.sql) in the Supabase SQL Editor. New installations using `supabase/schema.sql` already include these changes. The migration adds reset digest/expiry/cooldown fields and a service-role-only database function for atomic password updates and session revocation. SQLite migrates automatically.
2. Configure outbound email on the **backend**. On Render Free, use `RESEND_API_KEY` and `RESEND_FROM` as described below. Alternatively, on hosting that permits SMTP, use `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM`; the SMTP sender falls back to `SMTP_USER` if `SMTP_FROM` is empty.
3. Set backend `PASSWORD_RESET_URL=https://your-website.example/reset-password`. When omitted, the backend uses the origin of `DASHBOARD_URL` or `PAYSTACK_CALLBACK_URL`, with `/reset-password`. Local development falls back to `http://localhost:3000/reset-password`. Non-local links require HTTPS. The app never constructs reset links from untrusted request headers.
4. Redeploy the Python API and dashboard. Local development uses `cd dashboard && npm run dev`.

The UI reports recovery as unavailable when email settings or the required database fields are missing. This feature uses the application's existing custom accounts; Supabase Auth's separate password-recovery settings do not change these passwords.

## Render Free email setup

[Render Free blocks outbound SMTP on ports 25, 465, and 587](https://render.com/docs/free#other-limitations). Gmail SMTP credentials can work locally and still time out on the deployed service. The app supports [Resend's HTTPS email API](https://resend.com/docs/api-reference/emails/send-email), which does not use these ports and requires no new Python dependency.

1. Create a Resend API key and verify a sending domain in Resend. For real users, `RESEND_FROM` must use that verified domain. The `onboarding@resend.dev` test sender can send only to the Resend account owner's email; it is not a production sender. See [Resend sender restrictions](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain).
2. In **Render → your Python API service → Environment**, add:

   ```env
   RESEND_API_KEY=re_your_actual_key
   RESEND_FROM=Clearing Desk <no-reply@your-verified-domain.com>
   PASSWORD_RESET_URL=https://logistic-orpin-phi.vercel.app/reset-password
   ```

   Use your current frontend domain if it differs. Keep the API key on the backend; never use a `NEXT_PUBLIC_` prefix. Values in local `.env` do not automatically configure Render.
3. Deploy the updated backend with these environment values. Resend takes priority over existing SMTP settings for outbound app email, including reset links and quote copies. A partially configured Resend setup reports configuration failure; delivery does not fall back to blocked SMTP after provider rejection.
4. Open the deployed website's `/desk?mode=forgot-password`, enter the email of an account in the app's `public.users` table, and request a link. Supabase Authentication's Users screen manages separate accounts; its magic links do not reset this app's passwords. Requests remain limited to one per account per minute.
5. Check Resend's email dashboard for acceptance, delivery, rejection, or bounce status; provider acceptance alone does not guarantee arrival in the inbox. App logs identify HTTP 401 (key), 403 (sender/test-recipient restrictions), and 429 (provider quota) without logging recipients, reset tokens, or response bodies. Check the inbox and spam folder.

The confirmation shown after requesting a reset is deliberately the same for registered and unknown addresses. It acknowledges the request, not successful delivery. The app sends in a background task; a process restart during delivery can lose that attempt, and no automatic provider retry is performed. Request another link after one minute if needed.

## Behavior and verification

- Requests return the same confirmation for registered and unknown emails. Account lookup and email delivery run after the response. No reset token is returned by the API.
- Links contain a cryptographically random 256-bit token. Only its SHA-256 digest is stored. Links expire after 30 minutes, work once, and are replaced when a newer link is issued. Requests are limited to one per account per minute.
- The token travels in the URL fragment, stays out of server request logs, and is removed from browser history on opening the form. The reset page sets a no-referrer policy.
- New passwords require 12–128 characters. The client checks confirmation. The server consumes the token, updates the password, and revokes existing sign-in sessions in one database transaction. Resetting does not automatically sign the user in.
- Tests use temporary SQLite storage and mocked/captured email. No real reset messages are sent by verification. Cloud adapter tests verify request contracts; the Supabase SQL migration must be applied separately.

Run recovery checks from the project root:

```bash
.venv/bin/python -m unittest tests.test_password_reset -q
.venv/bin/python -m unittest tests.test_email_delivery -q
```

These choices follow the [OWASP password recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
