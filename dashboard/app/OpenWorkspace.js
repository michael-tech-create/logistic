"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Alert, Button, CircularProgress, Container, Typography } from "@mui/material";
import Auth from "./Auth";
import { request } from "./workflow.mjs";

const PROFILE = "quote_profile";
const Workspace = dynamic(() => import("./DeskApp"), {
  loading: () => <Opening />,
});

function Opening() {
  return <Container maxWidth="sm" sx={{ py: 12, textAlign: "center" }}><CircularProgress size={28} /><Typography role="status" sx={{ mt: 2 }}>Opening your workspace…</Typography></Container>;
}

function readProfile() {
  try {
    const profile = JSON.parse(window.localStorage.getItem(PROFILE) || "null");
    return profile?.id ? profile : null;
  } catch {
    return null;
  }
}

function remember(user) {
  const { token, ...profile } = user;
  if (profile.id) window.localStorage.setItem(PROFILE, JSON.stringify(profile));
  return profile;
}

function clearSession() {
  window.localStorage.removeItem("quote_token");
  window.localStorage.removeItem(PROFILE);
}

export default function OpenWorkspace() {
  const [session, setSession] = useState(null);
  const [phase, setPhase] = useState("check");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const token = window.localStorage.getItem("quote_token");
    if (!token) { setPhase("auth"); return undefined; }
    // Load the desk while the session check runs, instead of after it.
    const workspace = import("./DeskApp");
    const cached = readProfile();
    if (cached) { setSession({ ...cached, token }); setPhase("ready"); }
    request(token, "/v1/me", { timeout: 12000 }).then((user) => {
      if (!active) return;
      remember(user);
      setSession({ ...user, token });
      setPhase("ready");
    }).catch((err) => {
      if (!active) return;
      if (err.status === 401) { clearSession(); setSession(null); setPhase("auth"); return; }
      if (!cached) { setError(err.message); setPhase("error"); }
    });
    workspace.catch(() => {});
    return () => { active = false; };
  }, []);

  function enter(next) {
    window.localStorage.setItem("quote_token", next.token);
    remember(next);
    setSession(next);
    setError("");
    setPhase("ready");
  }

  function signOut() {
    clearSession();
    setSession(null);
    setPhase("auth");
    window.location.hash = "";
  }

  if (phase === "check") return <Opening />;
  if (phase === "error") return <Container maxWidth="sm" sx={{ py: 12, textAlign: "center" }}><Alert severity="error" action={<Button color="inherit" onClick={() => window.location.reload()}>Retry</Button>}>{error}</Alert></Container>;
  if (phase === "auth" || !session) return <Auth onSession={enter} />;
  return <Workspace key={session.id} token={session.token} initialUser={session} onSignOut={signOut} />;
}
