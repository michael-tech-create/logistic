"use client";
import { useEffect, useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import { ExpandMore } from "@mui/icons-material";
import { request } from "./workflow.mjs";

const setupInstructions = `WhatsApp intake — one-time server setup
Access needed: the API hosting account, the project's Supabase account (if hosted), and waapi.app.
1. In Supabase's SQL editor, run supabase/operations.sql from this project after supabase/schema.sql. Local SQLite creates its tables automatically.
2. In waapi.app, connect the business WhatsApp number to an instance. Get the API token and numeric instance ID.
3. In the Python API service's environment settings, save:
   WAAPI_TOKEN: your WaAPI API token
   WAAPI_INSTANCE_ID: your numeric instance ID
   WAAPI_WEBHOOK_SECRET: a new random secret of at least 32 characters
   WHATSAPP_BUSINESS_NUMBER: international digits only, with country code and no + or spaces
   Generate the secret with a password manager. Keep credentials in the server environment, not the dashboard or source code.
4. In WaAPI, register the message event webhook as https://YOUR_API/whatsapp/webhook/YOUR_SECRET. Replace YOUR_API with the public HTTPS API host and YOUR_SECRET with the exact WAAPI_WEBHOOK_SECRET. Keep the complete URL private.
5. Restart/redeploy the API to load the settings. Ensure python automate.py runs alongside it (the project's container already does this).
6. In Connections → WhatsApp intake, click Check setup again. Create a connection code and send its /link command from your own WhatsApp to the business number within 10 minutes. Wait for the Connected reply, then refresh connections.
7. Send a sample text quote and check that it appears in the quote inbox. Server setting checks alone do not verify provider login or webhook delivery.
If no reply arrives, check the provider session, message webhook, API availability, and intake worker. WAAPI_CHAT_ID, if set, restricts replies to that recipient.
For scanned PDFs, photos, and voice notes, configure GEMINI_API_KEYS on the server.`;

const checks = [
  ["storage", "Quote storage", "Database tables available"],
  ["provider_token", "WaAPI account", "API token saved"],
  ["instance_id", "WhatsApp instance", "Numeric instance ID saved"],
  ["webhook_secret", "Incoming message security", "Secret of at least 32 characters saved"],
  ["business_number", "Business WhatsApp number", "International phone number saved"],
];

export default function WhatsAppConnection({ token }) {
  const [status, setStatus] = useState(null);
  const [code, setCode] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() { setStatus(await request(token, "/v1/channels/whatsapp")); }
  async function run(callback) {
    setBusy(true); setError(""); setNotice("");
    try { await callback(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  useEffect(() => {
    let active = true;
    setStatus(null); setCode(null); setError(""); setNotice("");
    request(token, "/v1/channels/whatsapp").then((value) => { if (active) setStatus(value); }).catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [token]);
  const needsSetup = status && (!status.configured || status.checks?.business_number === false);
  return <Paper sx={{ p: { xs: 2, md: 3 }, border: 1, borderColor: "divider" }}>
    <Stack spacing={2}>
      <Typography variant="h2">WhatsApp intake</Typography>
      <Typography variant="body2" color="text.secondary">Connect your number, then send quote text, PDFs, images, or voice notes. Review the extracted quote in chat and download PDF or Excel files.</Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {notice && <Alert severity="success" role="status">{notice}</Alert>}
      {!status && !error && <Typography role="status">Checking WhatsApp setup…</Typography>}
      {needsSetup && <Alert severity="info">WhatsApp needs a one-time setup. You can do this yourself if you manage the hosting, database, and WaAPI accounts. Otherwise, copy the instructions below for your developer or server administrator.</Alert>}
      {status && <Accordion defaultExpanded={!status.configured} disableGutters>
        <AccordionSummary expandIcon={<ExpandMore />} aria-controls="whatsapp-setup-content" id="whatsapp-setup-heading"><Typography variant="h3">One-time setup guide</Typography></AccordionSummary>
        <AccordionDetails id="whatsapp-setup-content"><Stack spacing={2.5}>
          <Typography variant="body2">No application coding is needed. These settings are managed in your service accounts; this panel checks them after they are saved.</Typography>
          {status.checks && <Stack spacing={1} aria-label="Server setup checks">{checks.map(([key, title, description]) => <Stack key={key} direction={{ xs: "column", sm: "row" }} gap={1} justifyContent="space-between" alignItems={{ sm: "center" }}>
            <Box><Typography variant="body2">{title}</Typography><Typography variant="caption" color="text.secondary">{description}</Typography></Box>
            <Chip size="small" variant="outlined" color={status.checks[key] ? "success" : "warning"} label={status.checks[key] ? "Available" : "Needs setup"} sx={{ alignSelf: "flex-start" }} />
          </Stack>)}</Stack>}
          <Box><Typography variant="h3">1. Prepare your service accounts</Typography><Typography variant="body2" sx={{ mt: 1 }}>Have access to the API hosting account, your project’s Supabase database, and waapi.app. In WaAPI, connect the business WhatsApp number to an instance. Keep your own WhatsApp number available for the final test.</Typography></Box>
          <Box><Typography variant="h3">2. Save the server settings</Typography><Typography variant="body2" sx={{ mt: 1 }}>The person managing the server prepares the database and saves the provider details in the API host’s environment settings. Open the server instructions below for the exact fields.</Typography></Box>
          <Box><Typography variant="h3">3. Turn on incoming messages</Typography><Typography variant="body2" sx={{ mt: 1 }}>In WaAPI, add the message webhook using your API address and the secret saved on the server. A webhook forwards incoming WhatsApp messages to your desk. Restart the API, then click “Check setup again”.</Typography></Box>
          <Accordion disableGutters><AccordionSummary expandIcon={<ExpandMore />} aria-controls="whatsapp-server-content" id="whatsapp-server-heading"><Typography>Server instructions</Typography></AccordionSummary><AccordionDetails id="whatsapp-server-content"><Typography component="pre" variant="body2" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", m: 0 }}>{setupInstructions}</Typography></AccordionDetails></Accordion>
          <Stack direction="row" flexWrap="wrap" gap={1}>
            <Button variant="outlined" disabled={busy} onClick={() => run(async () => { await navigator.clipboard.writeText(setupInstructions); setNotice("Setup instructions copied. Share them with the person managing your server."); })}>Copy setup instructions</Button>
            <Button disabled={busy} onClick={() => run(refresh)}>Check setup again</Button>
          </Stack>
          <Typography variant="body2" color="text.secondary">These checks confirm saved settings and database access. The connection test below confirms that messages can reach your desk.</Typography>
        </Stack></AccordionDetails>
      </Accordion>}
      {status && <Box><Typography variant="h3">Connect your own WhatsApp</Typography><Typography variant="body2" sx={{ mt: 1 }}>{status.configured ? "Create a code, then send the command from your own WhatsApp to the business number. Wait for the Connected reply and refresh to see your number below." : "Complete the server setup above to unlock your connection code."}</Typography></Box>}
      <Stack direction="row" flexWrap="wrap" gap={1}>
        <Button variant="outlined" disabled={busy || !status?.configured} onClick={() => run(async () => setCode(await request(token, "/v1/channels/whatsapp/link", { method: "POST" })))}>Create connection code</Button>
        {status?.url && <Button href={status.url} target="_blank" rel="noopener noreferrer">Open WhatsApp</Button>}
        <Button disabled={busy} onClick={() => run(refresh)}>{busy ? "Working…" : "Refresh connections"}</Button>
      </Stack>
      {code && <Box><Typography variant="body2">Send this command to the business WhatsApp number within 10 minutes. It works once.</Typography><Typography component="code" sx={{ display: "block", overflowWrap: "anywhere", p: 2, bgcolor: "surface.soft", my: 1 }}>{code.command}</Typography><Button disabled={busy} onClick={() => run(async () => { await navigator.clipboard.writeText(code.command); setNotice("Command copied. Send it to the business number in WhatsApp."); })}>Copy command</Button></Box>}
      {status?.links?.map(({ phone }) => <Stack key={phone} direction="row" justifyContent="space-between" alignItems="center"><Typography variant="body2">+{phone}</Typography><Button color="error" disabled={busy} onClick={() => run(async () => { await request(token, "/v1/channels/whatsapp/disconnect", { method: "POST", body: JSON.stringify({ phone }) }); await refresh(); })}>Disconnect</Button></Stack>)}
      {!!status?.links?.length && <Alert severity="success">A number is linked. Send a sample text quote and check your quote inbox to test intake.</Alert>}
      {status?.configured && <Typography variant="body2" color="text.secondary">No reply? Ask the server administrator to check the WaAPI connection, message webhook, and intake worker. You can still upload quotes directly while setup is being resolved.</Typography>}
    </Stack>
  </Paper>;
}
