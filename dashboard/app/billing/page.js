"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Alert, Button, CircularProgress, Container, Paper, Stack, Typography } from "@mui/material";
import { request } from "../workflow.mjs";
import Brand from "../Brand";

function BillingReturn() {
  const params = useSearchParams();
  const reference = params.get("reference") || params.get("trxref") || "";
  const [state, setState] = useState("checking");
  const [message, setMessage] = useState("");
  const verify = useCallback(async () => {
    const token = window.localStorage.getItem("quote_token");
    if (!reference) { setState("error"); setMessage("No payment reference was returned. Return to Settings to start checkout again."); return; }
    if (!token) { setState("error"); setMessage("Sign in to your workspace, then reopen this payment link to confirm your payment."); return; }
    setState("checking");
    try {
      const payload = await request(token, "/v1/billing/verify", { method: "POST", body: JSON.stringify({ reference }) });
      setState("success"); setMessage(`Payment confirmed. You now have ${payload.quota_remaining} parses available.`);
    } catch (error) { setState("error"); setMessage(error.message); }
  }, [reference]);
  useEffect(() => { verify(); }, [verify]);
  return <Container component="main" maxWidth="sm" sx={{ py: 8 }}><Paper variant="outlined" sx={{ p: 4 }}><Stack spacing={3}>
    <Brand /><Typography variant="overline" color="text.secondary">SUBSCRIPTION</Typography><Typography variant="h1" sx={{ fontSize: 28 }}>{state === "checking" ? "Confirming your payment" : state === "success" ? "You’re ready to continue" : "Payment needs a check"}</Typography>
    {state === "checking" ? <Stack direction="row" spacing={2} alignItems="center" role="status"><CircularProgress size={22} /><Typography variant="body2">Checking the payment with Paystack. Please wait.</Typography></Stack> : <Alert severity={state === "success" ? "success" : "error"}>{message}</Alert>}
    <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>Reference: {reference || "Not provided"}</Typography>
    <Stack direction="row" spacing={1}>{state === "error" && reference && <Button variant="outlined" onClick={verify}>Retry confirmation</Button>}<Button variant="contained" href={state === "success" ? "/desk#quotes" : "/desk#settings"}>{state === "success" ? "Return to quotes" : "Back to workspace"}</Button></Stack>
  </Stack></Paper></Container>;
}

export default function BillingPage() {
  return <Suspense fallback={<Typography role="status" sx={{ p: 4 }}>Opening your payment result…</Typography>}><BillingReturn /></Suspense>;
}
