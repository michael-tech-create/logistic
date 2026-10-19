"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, LinearProgress, Stack, Step, StepLabel, Stepper, Tab, Tabs, TextField, Typography } from "@mui/material";
import { Close, DescriptionOutlined, UploadFileOutlined } from "@mui/icons-material";
import { request, validateFiles } from "./workflow.mjs";

export default function IntakeDialog({ token, quota, seed, onClose, onCreated, onSettings }) {
  const [tab, setTab] = useState(seed ? 1 : 0);
  const [text, setText] = useState(seed || "");
  const [files, setFiles] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);
  const errorBox = useRef(null);
  useEffect(() => { if (error) errorBox.current?.focus(); }, [error]);

  function choose(incoming) {
    const chosen = Array.from(incoming || []);
    const problem = validateFiles(chosen, quota);
    setFiles(chosen);
    setError(problem);
  }

  async function submit(event) {
    event.preventDefault();
    const problem = tab === 0 ? validateFiles(files, quota) : (!text.trim() ? "Paste the quote text before continuing." : quota < 1 ? "You have no parses left. Add more parses in Settings." : "");
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError("");
    try {
      let payload;
      if (tab === 0) {
        const body = new FormData();
        files.forEach((file) => body.append("files", file));
        payload = await request(token, "/v1/quotes/batch", { method: "POST", body });
      } else {
        const record = await request(token, "/v1/quotes/parse", { method: "POST", body: JSON.stringify({ text }) });
        payload = { records: [record] };
      }
      onCreated(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open fullWidth maxWidth="sm" onClose={busy ? undefined : onClose} aria-labelledby="intake-title">
      <DialogTitle id="intake-title" sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        Add a quote
        <IconButton aria-label="Close add quote" onClick={onClose} disabled={busy}><Close /></IconButton>
      </DialogTitle>
      <DialogContent>
        <Stepper activeStep={0} alternativeLabel sx={{ my: 2 }}>
          {["Add quote", "Check details", "Export"].map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
        </Stepper>
        <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>Start with the carrier’s original quote. You’ll check the extracted route and charges before preparing the client file.</Typography>
        {error && <Alert severity="error" ref={errorBox} tabIndex={-1} sx={{ mb: 2 }}>{error}</Alert>}
        {quota === 0 && <Alert severity="warning" sx={{ mb: 2 }} action={<Button color="inherit" onClick={onSettings}>Add parses</Button>}>You have no parses left.</Alert>}
        <Tabs value={tab} onChange={(_, value) => { setTab(value); setError(""); }} aria-label="Quote source" sx={{ borderBottom: 1, borderColor: "divider", mb: 3 }}>
          <Tab id="source-files" aria-controls="files-panel" label="Upload files" disabled={busy} />
          <Tab id="source-text" aria-controls="text-panel" label="Paste text" disabled={busy} />
        </Tabs>
        <Box component="form" id="intake-form" onSubmit={submit}>
          {tab === 0 ? (
            <Box role="tabpanel" id="files-panel" aria-labelledby="source-files">
              <Box onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); if (!busy) choose(event.dataTransfer.files); }} sx={{ border: "2px dashed", borderColor: dragging ? "primary.main" : "#c8d4c9", bgcolor: dragging ? "#edf5ee" : "#f8faf7", borderRadius: 2, textAlign: "center", p: 4 }}>
                <UploadFileOutlined sx={{ color: "primary.main", fontSize: 36, mb: 1 }} />
                <Typography fontWeight={650}>Drop your carrier quotes here</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>PDF or TXT · up to 10 MB per file</Typography>
                <Button variant="outlined" onClick={() => input.current?.click()} disabled={busy}>Browse files</Button>
                <input ref={input} type="file" accept=".pdf,.txt,application/pdf,text/plain" multiple hidden aria-label="Quote files" onChange={(event) => { choose(event.target.files); event.target.value = ""; }} />
              </Box>
              {!!files.length && <Stack spacing={1} sx={{ mt: 2 }}>{files.map((file, index) => (
                <Stack key={`${file.name}-${index}`} direction="row" spacing={1} alignItems="center" sx={{ border: 1, borderColor: "divider", borderRadius: 1, px: 1.5, py: .5 }}>
                  <DescriptionOutlined fontSize="small" color="action" />
                  <Typography variant="body2" sx={{ flex: 1, overflowWrap: "anywhere" }}>{file.name}</Typography>
                  <IconButton size="small" aria-label={`Remove ${file.name}`} disabled={busy} onClick={() => setFiles(files.filter((_, i) => i !== index))}><Close fontSize="small" /></IconButton>
                </Stack>
              ))}</Stack>}
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>Scanned PDFs may have no readable text. You can send those as a photo to Telegram.</Typography>
            </Box>
          ) : (
            <Box role="tabpanel" id="text-panel" aria-labelledby="source-text">
              <TextField label="Original quote text" fullWidth multiline minRows={9} value={text} onChange={(event) => setText(event.target.value)} disabled={busy} error={!!error && !text.trim()} helperText="Include the vendor, origin, destination, charges, and currencies. Keep mixed currencies as written." placeholder={"Provider: Carrier name\nOrigin: Shanghai\nDestination: Lagos\nFreight: USD 2,400\nTotal: USD 2,400"} />
            </Box>
          )}
        </Box>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 3 }}>
          <Typography variant="body2" color="text.secondary">{quota} parses available</Typography>
          <Chip size="small" variant="outlined" label={`${tab === 0 ? files.length : 1} parse${tab === 0 && files.length !== 1 ? "s" : ""} needed`} />
        </Stack>
        {busy && <Box role="status" aria-live="polite" sx={{ mt: 2 }}><LinearProgress /><Typography variant="body2" sx={{ mt: 1 }}>Reading your quote and preparing the details. This may take a moment.</Typography></Box>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button type="submit" form="intake-form" variant="contained" disabled={busy || quota < 1}>{busy ? "Reading quote…" : "Continue to check details"}</Button>
      </DialogActions>
    </Dialog>
  );
}
