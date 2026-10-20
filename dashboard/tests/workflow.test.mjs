import assert from "node:assert/strict";
import test from "node:test";
import { filterRecords, mergeRecords, missingDetails, money, request, reviewStatusOf, statusOf, validateFiles } from "../app/workflow.mjs";

const quote = (id, currency = "USD") => ({ record_id: id, commercial: { vendor_name: "Carrier", quote_reference_id: "REPEATED", currency, total_amount: 100 }, movement: { origin: { location_name: "Shanghai" }, destination: { location_name: "Lagos" } }, line_items: [{ description: "Freight", amount: 100 }] });

test("only an approved, unsent provider request offers submission", () => {
  assert.equal(reviewStatusOf({ kind: "pay", status: "approved" }).canSend, true);
  for (const status of ["pending", "executed", "processing", "execution_uncertain", "rejected"]) assert.ok(!reviewStatusOf({ kind: "pay", status }).canSend);
  assert.ok(!reviewStatusOf({ kind: "terminal", status: "approved" }).canSend);
  assert.match(reviewStatusOf({ kind: "clear", status: "approved" }).label, /Not sent/);
  assert.match(reviewStatusOf({ status: "executed" }).label, /Submitted/);
});

test("same reference across different quotes does not hide shipments", () => {
  assert.equal(mergeRecords([quote("a"), quote("b")], [quote("a"), quote("c")]).length, 3);
});
test("latest persisted record takes precedence over stale pack data", () => {
  const checked = { ...quote("a"), desk_review: { status: "reviewed" } };
  assert.equal(statusOf(mergeRecords([checked], [quote("a")])[0]).key, "reviewed");
});
test("missing route or charges blocks the checked state", () => {
  const incomplete = { ...quote("a"), movement: {}, desk_review: { status: "reviewed" } };
  assert.deepEqual(missingDetails(incomplete), ["origin", "destination"]);
  assert.equal(statusOf(incomplete).key, "incomplete");
  assert.equal(statusOf(quote("a")).key, "pending");
});
test("search and check filters compose", () => {
  const checked = { ...quote("b"), desk_review: { status: "reviewed" } };
  assert.equal(filterRecords([quote("a"), checked], "lagos", "reviewed")[0].record_id, "b");
  assert.equal(filterRecords([quote("a"), checked], "REPEATED", "unchecked")[0].record_id, "a");
  assert.equal(filterRecords([checked], "missing", "all").length, 0);
});
test("file validation catches unsupported, empty, oversized, and over-quota uploads", () => {
  assert.match(validateFiles([], 5), /Choose at least/);
  assert.match(validateFiles([{ name: "quote.csv", size: 3 }], 5), /PDF or TXT/);
  assert.match(validateFiles([{ name: "quote.txt", size: 0 }], 5), /empty/);
  assert.match(validateFiles([{ name: "quote.pdf", size: 11 * 1024 * 1024 }], 5), /10 MB/);
  assert.match(validateFiles([{ name: "quote.txt", size: 3 }], 0), /0 parses/);
  assert.equal(validateFiles([{ name: "QUOTE.PDF", size: 3 }], 1), "");
});
test("money keeps currencies explicit and never invents a missing zero", () => {
  assert.match(money("USD", 100), /^USD /);
  assert.match(money("NGN", 100), /^NGN /);
  assert.equal(money("NGN", undefined), "Not available");
  assert.match(money("NGN", 0), /0\.00/);
});
test("network failure provides a retry message instead of leaving a silent spinner", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  try { await assert.rejects(request("fixture", "/v1/inbox"), /Check your connection/); }
  finally { globalThis.fetch = original; }
});
test("a failed API proxy explains recovery rather than reporting a generic sign-in error", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response("Proxy unavailable", { status: 500 });
  try { await assert.rejects(request("", "/v1/auth/login"), /desk API is unavailable/); }
  finally { globalThis.fetch = original; }
});
test("server errors and quota status are preserved for recovery", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "No parses left" }), { status: 402 });
  try { await assert.rejects(request("fixture", "/v1/quotes/parse"), (error) => error.status === 402 && error.message === "No parses left"); }
  finally { globalThis.fetch = original; }
});

test("incorrect login credentials are not described as an expired session", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Email or password is wrong." }), { status: 401 });
  try { await assert.rejects(request("", "/v1/auth/login"), /Email or password is wrong/); }
  finally { globalThis.fetch = original; }
});
