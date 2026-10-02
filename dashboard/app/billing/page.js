"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Alert, Button, Container, Paper, Stack, Typography } from "@mui/material";
import { Suspense } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "";

function BillingReturn() {
  const params = useSearchParams();
  const reference = params.get("reference") || params.get("trxref") || "";
  const [message, setMessage] = useState("Confirming the Paystack payment…");
  const [ok, setOk] = useState(false);

  useEffect(() => {
    const token = window.localStorage.getItem("quote_token");
    if (!reference) {
      setMessage("Paystack did not return a payment reference.");
      return;
    }
    if (!token) {
      setMessage("Sign in on the desk first, then open this payment link again.");
      return;
    }
    fetch(`${API}/v1/billing/verify`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ reference }),
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Payment was not confirmed");
        setOk(true);
        setMessage(`Payment ${payload.reference} is confirmed. Parses left: ${payload.quota_remaining}.`);
      })
      .catch((error) => setMessage(error.message));
  }, [reference]);

  return (
    <Container maxWidth="sm" sx={{ py: 8 }}>
      <Paper sx={{ p: 4 }}>
        <Stack spacing={2}>
          <Typography variant="h4">Back from Paystack</Typography>
          <Alert severity={ok ? "success" : "info"}>{message}</Alert>
          <Typography variant="body2" color="text.secondary">Reference {reference || "—"}</Typography>
          <Button variant="contained" href="/">Return to the clearing desk</Button>
        </Stack>
      </Paper>
    </Container>
  );
}

export default function BillingPage() {
  return (
    <Suspense fallback={<Typography sx={{ p: 4 }}>Opening the payment result…</Typography>}>
      <BillingReturn />
    </Suspense>
  );
}
