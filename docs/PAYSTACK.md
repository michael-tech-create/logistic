# Checkout configuration and invalid-key errors

Checkout is initialized by the Python API using `PAYSTACK_SECRET_KEY`. A Paystack `401` with `invalid_Key` means the credential sent to Paystack was rejected. Updating the frontend callback URL does not repair this credential.

1. Open your Paystack dashboard and go to **Settings → API Keys & Webhooks**.
2. Copy the current **secret key** for the environment you need: `sk_test_…` for testing or `sk_live_…` for real payments. Public keys beginning `pk_` cannot authorize this backend checkout request. If necessary, generate a replacement secret key in Paystack.
3. Set `PAYSTACK_SECRET_KEY` on the **Python API**. For local development, update the project-root `.env`. For Render, update the API service's Environment setting and restart/redeploy the service. A local `.env` edit does not update Render. An inherited process environment value takes precedence over `.env`.
4. Keep `PAYSTACK_CALLBACK_URL` pointing to the frontend `/billing` page. For production, use your public HTTPS frontend origin. This setting is independent of API authentication.
5. Restart the backend after changing credentials. Locally, stop the running development command and run `cd dashboard && npm run dev` again.

Use the diagnostic from the project root:

```bash
.venv/bin/python paystack_diagnostics.py
.venv/bin/python paystack_diagnostics.py --live
```

The default check is offline. `--live` calls Paystack's read-only payment-session-timeout endpoint to validate authentication. Neither command prints the key, creates a checkout, or charges money. Run the command in the same environment as the failing API; checking local configuration cannot validate a separately configured Render service.

The backend normalizes surrounding whitespace and literal pasted quotes, rejects missing/public/malformed keys, and maps `401` to an actionable configuration error. Checkout, verification, and webhook signatures use the same normalized secret. Provider error text is redacted before returning it to the user. A correctly shaped secret can still be invalid, revoked, or from an incorrect copy; the read-only check distinguishes format from authentication.

Paystack also supports API-key IP allowlists. A `403` requires checking the server's allowed IPs and key permissions.

See the official [authentication documentation](https://paystack.com/docs/api/authentication/), [API key settings guide](https://support.paystack.com/en/articles/2123458), and [read-only integration endpoint](https://paystack.com/docs/api/integration/).
