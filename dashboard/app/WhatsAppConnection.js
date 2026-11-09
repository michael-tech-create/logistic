"use client";
import { useEffect, useState } from "react";
import { Alert, Box, Button, Divider, Paper, Stack, TextField, Typography } from "@mui/material";
import { request } from "./workflow.mjs";

export default function WhatsAppConnection({ token }) {
  const [status, setStatus] = useState(null);
  const [providerToken, setProviderToken] = useState("");
  const [instance, setInstance] = useState("");
  const [number, setNumber] = useState("");
  const [code, setCode] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  function accept(value) {
    setStatus(value); setInstance(value.instance_id || ""); setNumber(value.business_number || "");
  }
  async function refresh() { accept(await request(token, "/v1/channels/whatsapp")); }
  async function run(callback) {
    setBusy(true); setError(""); setNotice("");
    try { await callback(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  useEffect(() => {
    let active = true;
    setStatus(null); setProviderToken(""); setCode(null); setError(""); setNotice("");
    request(token, "/v1/channels/whatsapp").then((value) => { if (active) accept(value); }).catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [token]);
  async function save(event) {
    event.preventDefault();
    await run(async () => {
      const phone = number.replace(/[+\s()-]/g, "");
      if (!/^[0-9]{8,16}$/.test(phone)) throw new Error("Enter your number with its country code, using 8 to 16 digits.");
      try {
        await request(token, "/v1/channels/whatsapp/settings", { method: "PUT", body: JSON.stringify({ token: providerToken.trim() || null, instance_id: instance.trim(), business_number: phone }) });
      } catch (e) {
        // Refresh persisted progress after provider failures, preserving edits if refresh fails.
        try { await refresh(); } catch {}
        throw e;
      }
      setProviderToken(""); setCode(null); await refresh();
      setNotice("Details saved and webhook registered with WaAPI. Connect your own number below to test messages.");
    });
  }
  return <Paper sx={{ p: { xs: 2, md: 3 }, border: 1, borderColor: "divider" }}><Stack spacing={2.5}>
    <Typography variant="h2">Connect WhatsApp</Typography>
    <Typography variant="body2" color="text.secondary">Enter your WaAPI details. We’ll save them for this workspace, generate the security secret, and set up incoming messages automatically.</Typography>
    {error && <Alert severity="error">{error}</Alert>}
    {notice && <Alert severity="success" role="status">{notice}</Alert>}
    {!status && !error && <Typography role="status">Loading WhatsApp settings…</Typography>}
    {status?.storage_ready === false && <Alert severity="warning">{status.detail}</Alert>}
    {status && status.storage_ready !== false && <>
      {status.webhook_ready && <Alert severity="success">Your details are saved and WaAPI accepted the webhook setup. Send a test message below to confirm delivery.</Alert>}
      {status.settings_saved && !status.webhook_ready && <Alert severity="warning">Your details are saved, but setup is not confirmed. Check the fields and select Save and connect to retry.</Alert>}
      <Typography variant="h3">1. Enter your account details</Typography>
      <Typography variant="body2">Connect your business number in <a href="https://waapi.app" target="_blank" rel="noopener noreferrer">waapi.app</a>, then enter its details here. Your API token needs permission to update the instance.</Typography>
      <Box component="form" onSubmit={save} sx={{ maxWidth: 640 }}><Stack spacing={2}>
        <TextField label="WaAPI API token" type="password" autoComplete="new-password" value={providerToken} onChange={(e) => setProviderToken(e.target.value)} required={!status.token_saved} disabled={busy} helperText={status.token_saved ? "Leave blank to keep your saved token, or paste a replacement." : "Paste the API token from your WaAPI account. It is hidden after saving."} fullWidth />
        <TextField label="Instance ID" value={instance} onChange={(e) => setInstance(e.target.value)} required disabled={busy} slotProps={{ htmlInput: { inputMode: "numeric", pattern: "[0-9]{1,30}" } }} helperText="The numeric ID of the instance connected to your business number." fullWidth />
        <TextField label="Business WhatsApp number" type="tel" placeholder="e.g. +234 800 000 0000" value={number} onChange={(e) => setNumber(e.target.value)} required disabled={busy} helperText="Include your country code. Use the number connected in WaAPI." fullWidth />
        <Typography variant="body2" color="text.secondary">Save and connect sets this app as the instance’s message webhook, replacing any existing webhook on that instance.</Typography>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Connecting…" : "Save and connect"}</Button>
      </Stack></Box>
      <Divider />
      <Typography variant="h3">2. Connect and test your own number</Typography>
      <Typography variant="body2">Create a code and send the command from your own WhatsApp to the business number. Wait for the “Connected” reply, then send a sample text quote and check your quote inbox.</Typography>
      <Stack direction="row" gap={1} flexWrap="wrap">
        <Button variant="outlined" disabled={busy || !status.configured} onClick={() => run(async () => setCode(await request(token, "/v1/channels/whatsapp/link", { method: "POST" })))}>Create connection code</Button>
        {status.url && <Button href={status.url} target="_blank" rel="noopener noreferrer">Open WhatsApp</Button>}
      </Stack>
      {code && <Box><Typography variant="body2">This code works once and expires in 10 minutes.</Typography><Typography component="code" sx={{ display: "block", overflowWrap: "anywhere", p: 2, bgcolor: "surface.soft", my: 1 }}>{code.command}</Typography><Button disabled={busy} onClick={() => run(async () => { await navigator.clipboard.writeText(code.command); setNotice("Command copied. Send it to your business number in WhatsApp."); })}>Copy command</Button></Box>}
      {status.links?.map(({ phone }) => <Stack key={phone} direction="row" justifyContent="space-between" alignItems="center"><Typography variant="body2">Linked: +{phone}</Typography><Button color="error" disabled={busy} onClick={() => run(async () => { await request(token, "/v1/channels/whatsapp/disconnect", { method: "POST", body: JSON.stringify({ phone }) }); await refresh(); })}>Disconnect</Button></Stack>)}
    </>}
    <Button disabled={busy} sx={{ alignSelf: "flex-start" }} onClick={() => run(refresh)}>Refresh connection status</Button>
  </Stack></Paper>;
}
