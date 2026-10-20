"use client";

import { useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControlLabel, IconButton, Stack, Step, StepLabel, Stepper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from "@mui/material";
import { CheckCircleOutline, Close, DownloadOutlined, ExpandMore, OpenInNew } from "@mui/icons-material";
import { missingDetails, money, request, saveDownload, statusOf } from "./workflow.mjs";

function Detail({ label, children }) {
  return <Box><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="body2" fontWeight={600} sx={{ overflowWrap: "anywhere" }}>{children || "Not provided"}</Typography></Box>;
}

export default function QuoteDialog({ token, record, onClose, onUpdate, onCorrect, onDelete }) {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [accounts, setAccounts] = useState({ trucker_account: "", agent_account: "", customs_account: "" });
  const status = statusOf(record);
  const commercial = record.commercial || {};
  const movement = record.movement || {};
  const missing = missingDetails(record);
  const checked = status.key === "reviewed";
  const official = record.fx?.cbn;

  async function perform(action, callback) {
    setBusy(action); setError(""); setNote("");
    try { await callback(); } catch (err) { setError(err.message); } finally { setBusy(""); }
  }
  function download(kind) {
    perform(kind, async () => {
      const blob = await request(token, `/v1/quotes/${record.record_id}/export/${kind}`, { download: true });
      saveDownload(blob, `${record.record_id}.${kind}`);
      setNote(`${kind.toUpperCase()} download started.`);
    });
  }
  function operation(path, body, message) {
    perform(path, async () => {
      await request(token, path, { method: "POST", body: JSON.stringify({ ...body, record_id: record.record_id }) });
      setNote(message);
    });
  }
  return (
    <Dialog open fullWidth maxWidth="md" onClose={busy ? undefined : onClose} aria-labelledby="quote-title">
      <DialogTitle id="quote-title" sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 2 }}>
        <Box><Typography component="span" fontWeight={700}>{commercial.vendor_name || "Quote details"}</Typography><Typography variant="body2" color="text.secondary">{commercial.quote_reference_id || record.source_file || record.record_id}</Typography></Box>
        <IconButton aria-label="Close quote details" disabled={!!busy} onClick={onClose}><Close /></IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Stepper activeStep={checked ? 2 : 1} alternativeLabel sx={{ mb: 3 }}>
          {["Add quote", "Check details", "Export"].map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
        </Stepper>
        <Stack spacing={3}>
          {error && <Alert severity="error">{error}</Alert>}
          {note && <Alert severity="success" role="status">{note}</Alert>}
          {!!missing.length && <Alert severity="warning" action={<Button color="inherit" onClick={() => onCorrect(record)}>Correct quote</Button>}>Missing {missing.join(", ")}. Add these to the original text and parse it again before marking it checked.</Alert>}
          <Stack direction="row" justifyContent="space-between" alignItems="center" useFlexGap flexWrap="wrap" gap={1}>
            <Chip label={status.label} color={status.color} size="small" variant="outlined" />
            <Typography variant="caption" color="text.secondary">{checked ? `Checked by ${record.desk_review.reviewed_by}` : "Check against the original carrier quote"}</Typography>
          </Stack>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(4, 1fr)" }, gap: 2, p: 2.5, bgcolor: "surface.soft", borderRadius: 2 }}>
            <Detail label="Origin">{movement.origin?.location_name}</Detail>
            <Detail label="Destination">{movement.destination?.location_name}</Detail>
            <Detail label="Mode">{movement.mode}</Detail>
            <Detail label="Quote total">{money(commercial.currency, commercial.total_amount)}</Detail>
            <Detail label="Valid until">{commercial.valid_until}</Detail>
            <Detail label="Incoterms">{commercial.incoterms}</Detail>
            <Detail label="Payment terms">{commercial.payment_terms}</Detail>
            <Detail label="Transit time">{movement.est_transit_days ? `${movement.est_transit_days} days` : null}</Detail>
          </Box>
          <Box>
            <Typography variant="h2" sx={{ mb: 1.5 }}>Charge breakdown</Typography>
            {record.fx?.mixed && <Alert severity="info" sx={{ mb: 2 }}>Mixed currencies: the quote total contains local NGN charges. USD freight is kept separately in the cash estimate below.</Alert>}
            <TableContainer><Table size="small" aria-label="Quote charge breakdown"><TableHead><TableRow><TableCell>Description</TableCell><TableCell>Category</TableCell><TableCell align="right">Amount</TableCell></TableRow></TableHead>
              <TableBody>{(record.line_items || []).map((item, index) => <TableRow key={index}><TableCell>{item.description}</TableCell><TableCell>{item.category}</TableCell><TableCell align="right" sx={{ whiteSpace: "nowrap" }}>{money(item.currency || commercial.currency, item.amount)}</TableCell></TableRow>)}
                <TableRow><TableCell colSpan={2} sx={{ fontWeight: 700 }}>Quoted total</TableCell><TableCell align="right" sx={{ fontWeight: 700, whiteSpace: "nowrap" }}>{money(commercial.currency, commercial.total_amount)}</TableCell></TableRow>
              </TableBody></Table></TableContainer>
          </Box>
          {record.fx && <Box><Typography variant="h2" sx={{ mb: 1.5 }}>Cash estimate</Typography>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 }}>{["cbn", "parallel"].map((tier) => <Box key={tier} sx={{ p: 2, border: 1, borderColor: "divider", borderRadius: 1 }}><Typography variant="body2" color="text.secondary">{tier === "cbn" ? "Official / mid-market estimate" : "Parallel cash estimate"}</Typography><Typography variant="h6" sx={{ mt: .5 }}>{money("NGN", record.fx[tier]?.NGN)}</Typography><Typography variant="caption" color="text.secondary">{record.fx[tier]?.usd_ngn ? `USD/NGN ${Number(record.fx[tier].usd_ngn).toLocaleString()}` : "No usable rate available"}</Typography></Box>)}</Box>
            {record.fx.fx_anomaly && <Alert severity="warning" sx={{ mt: 1.5 }}>A currency calculation needs attention. Check the original amounts and your rates in Settings.</Alert>}
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>Planning estimates, not a customs assessment. {record.demurrage?.reason}</Typography>
          </Box>}
          {!!record.extraction_flags?.length && <Accordion disableGutters variant="outlined"><AccordionSummary expandIcon={<ExpandMore />}><Typography variant="body2" fontWeight={600}>Extraction notes ({record.extraction_flags.length})</Typography></AccordionSummary><AccordionDetails><Stack component="ul" spacing={1} sx={{ m: 0, pl: 2 }}>{record.extraction_flags.map((flag, index) => <Typography key={index} component="li" variant="body2">{flag}</Typography>)}</Stack></AccordionDetails></Accordion>}
          {record.source_text && <Accordion disableGutters variant="outlined"><AccordionSummary expandIcon={<ExpandMore />}><Typography variant="body2" fontWeight={600}>Original quote text</Typography></AccordionSummary><AccordionDetails><Typography component="pre" variant="body2" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: "inherit" }}>{record.source_text}</Typography><Button onClick={() => onCorrect(record)} startIcon={<OpenInNew />}>Correct text and parse again</Button><Typography variant="caption" display="block" color="text.secondary">Creates a new quote and uses one parse. The original stays in your inbox.</Typography></AccordionDetails></Accordion>}
          <Divider />
          {checked ? <Alert severity="success" icon={<CheckCircleOutline />}>Quote checked. You can now export the client file. This check does not approve a payment or customs release.</Alert> : <Box><FormControlLabel control={<Checkbox checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={!!busy || !!missing.length} />} label="I have checked the route, currency, charges, and extraction notes against the original quote." /><Typography variant="caption" color="text.secondary" display="block" sx={{ ml: 4 }}>This saves your check to the quote. It does not send money or clear cargo.</Typography></Box>}
          {checked && <Accordion disableGutters variant="outlined"><AccordionSummary expandIcon={<ExpandMore />}><Typography variant="body2" fontWeight={600}>Optional: finance and settlement records</Typography></AccordionSummary><AccordionDetails>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>These actions record a request or ledger entry for this quote. They do not transfer funds.</Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <Button variant="outlined" disabled={!!busy || !record.financing?.principal_ngn} onClick={() => operation("/v1/finance/apply", { principal_ngn: record.financing.principal_ngn }, "Duty finance request recorded for this quote.")}>Request duty finance</Button>
              <Button variant="outlined" disabled={!!busy || !official?.NGN} onClick={() => operation("/v1/escrow", { amount_ngn: official.NGN, action: "hold" }, "Escrow hold recorded. No funds were transferred.")}>Record escrow hold</Button>
              <Button disabled={!!busy || !official?.NGN} onClick={() => operation("/v1/escrow", { amount_ngn: official.NGN, action: "release" }, "Escrow release recorded. No funds were transferred.")}>Record release</Button>
            </Stack>
            <Typography variant="h3" sx={{ mt: 3, mb: 1 }}>Payout plan</Typography><Stack spacing={1.5}>{Object.keys(accounts).map((key) => <TextField key={key} size="small" label={key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())} value={accounts[key]} onChange={(event) => setAccounts({ ...accounts, [key]: event.target.value })} disabled={!!busy} />)}<Button variant="outlined" disabled={!!busy || !Object.values(accounts).every((value) => value.trim())} onClick={() => operation("/v1/payouts", accounts, "Payout plan saved for this quote. No transfer was made.")}>Save payout plan</Button></Stack>
          </AccordionDetails></Accordion>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ p: 2.5, flexWrap: "wrap", gap: 1 }}>
        <Button color="error" onClick={() => onDelete(record)} disabled={!!busy} sx={{ mr: "auto" }}>Delete quote</Button>
        {!checked && <Button onClick={() => onCorrect(record)} disabled={!!busy}>Correct quote</Button>}
        {checked ? <><Button variant="outlined" startIcon={<DownloadOutlined />} disabled={!!busy} onClick={() => download("xlsx")}>Excel</Button><Button variant="contained" startIcon={<DownloadOutlined />} disabled={!!busy} onClick={() => download("pdf")}>{busy === "pdf" ? "Preparing…" : "Download PDF"}</Button></> : <Button variant="contained" disabled={!confirmed || !!busy || !!missing.length} onClick={() => perform("review", async () => { const updated = await request(token, `/v1/quotes/${record.record_id}/review`, { method: "POST" }); onUpdate(updated); })}>{busy === "review" ? "Saving check…" : "Mark checked and continue"}</Button>}
      </DialogActions>
    </Dialog>
  );
}
