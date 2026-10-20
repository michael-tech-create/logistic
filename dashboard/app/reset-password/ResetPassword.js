"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Container, Paper, Stack, TextField, Typography } from "@mui/material";
import { request } from "../workflow.mjs";
import Brand from "../Brand";

export default function ResetPassword() {
  const [token, setToken] = useState("");
  const [ready, setReady] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    // Keep the bearer credential out of access logs, referrers, and history.
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const value = fragment.get("token") || "";
    // React Strict Mode reruns effects; preserve the first read after removing it.
    setToken((current) => value || current);
    window.history.replaceState(null, "", window.location.pathname);
    setReady(true);
  }, []);

  async function submit(event) {
    event.preventDefault(); setError("");
    if (password.length < 12 || password.length > 128) { setError("Use a password between 12 and 128 characters."); return; }
    if (password !== confirmation) { setError("The passwords don’t match. Enter the same password in both fields."); return; }
    setBusy(true);
    try {
      await request("", "/v1/auth/reset-password", { method: "POST", body: JSON.stringify({ token, password }) });
      window.localStorage.removeItem("quote_token");
      setToken(""); setPassword(""); setConfirmation(""); setDone(true);
    } catch (error) { setError(error.message); } finally { setBusy(false); }
  }

  return <Container component="main" maxWidth="sm" sx={{ py: { xs: 5, md: 10 } }}><Paper variant="outlined" sx={{ p: { xs: 3, sm: 4 } }}><Stack spacing={3}>
    <Brand />
    <Typography variant="h1" sx={{ fontSize: 30 }}>{done ? "Password reset" : "Choose a new password"}</Typography>
    {!ready ? <Typography role="status">Opening your reset link…</Typography> : done ? <><Alert severity="success" role="status">Your password has been reset. Sign in with your new password. Previous sign-in sessions have been closed.</Alert><Button variant="contained" href="/desk">Back to sign in</Button></> : !token ? <><Alert severity="warning">This link is missing its reset code. Open the full link from your email or request a new one.</Alert><Button href="/desk?mode=forgot-password" variant="contained">Request a new reset link</Button></> : <>
      <Typography variant="body2" color="text.secondary">Use a password between 12 and 128 characters. This link expires 30 minutes after it was requested.</Typography>
      {error && <Alert severity="error">{error}</Alert>}
      <Stack component="form" spacing={2.5} onSubmit={submit}>
        <TextField label="New password" type="password" required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} slotProps={{ htmlInput: { minLength: 12, maxLength: 128 } }} />
        <TextField label="Confirm new password" type="password" required autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} disabled={busy} slotProps={{ htmlInput: { minLength: 12, maxLength: 128 } }} />
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Resetting password…" : "Reset password"}</Button>
        <Button href="/desk?mode=forgot-password" disabled={busy}>Request a new link</Button>
      </Stack>
    </>}
  </Stack></Paper></Container>;
}
