"""Paystack request contracts with mocked responses; no payments or live calls."""

import hashlib
import hmac
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from api import billing


class Response:
    def __init__(self, payload): self.payload = payload
    def read(self): return json.dumps(self.payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False


class BillingConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"PAYSTACK_SECRET_KEY": "sk_test_fixturekey"}))

    def test_checkout_uses_secret_authorization_and_correct_plan_amount(self):
        for plan, amount in (("quote-200", 1500000), ("quote-1000", 5000000)):
            with self.subTest(plan=plan), patch("api.billing.urllib.request.urlopen", return_value=Response({"status": True, "data": {"authorization_url": "https://checkout.paystack.com/fixture", "reference": "fixture"}})) as provider:
                result = billing.initialize_checkout("owner@example.test", "https://desk.test/billing", plan)
                request = provider.call_args.args[0]
                self.assertEqual(request.get_header("Authorization"), "Bearer sk_test_fixturekey")
                self.assertEqual(request.get_method(), "POST")
                payload = json.loads(request.data)
                self.assertEqual(payload["amount"], amount)
                self.assertEqual(payload["metadata"]["plan"], plan)
                self.assertEqual(result["reference"], "fixture")

    def test_missing_public_or_malformed_keys_fail_before_any_api_request(self):
        for key in ("", "pk_test_fixturekey", "Bearer sk_test_fixturekey", "sk_test_your_key", "sk_test_a\nb"):
            with self.subTest(key=key), patch.dict(os.environ, {"PAYSTACK_SECRET_KEY": key}), patch("api.billing.urllib.request.urlopen") as provider:
                with self.assertRaises(billing.PaystackConfigurationError): billing.initialize_checkout("owner@example.test", "https://desk.test/billing")
                provider.assert_not_called()

    def test_pasted_quotes_and_whitespace_are_normalized_consistently(self):
        with patch.dict(os.environ, {"PAYSTACK_SECRET_KEY": ' "sk_test_fixturekey" \n'}), patch("api.billing.urllib.request.urlopen", return_value=Response({"status": True, "data": {}})) as provider:
            billing._request("/integration/payment_session_timeout")
            self.assertEqual(provider.call_args.args[0].get_header("Authorization"), "Bearer sk_test_fixturekey")
            body = b'{"event":"charge.success"}'
            signature = hmac.new(b"sk_test_fixturekey", body, hashlib.sha512).hexdigest()
            self.assertTrue(billing.verify_signature(body, signature))
            self.assertFalse(billing.verify_signature(body, "incorrect"))

    def test_paystack_401_is_an_actionable_configuration_error(self):
        error = urllib.error.HTTPError(billing.PAYSTACK_INIT, 401, "Unauthorized", {}, io.BytesIO(b'{"status":false,"message":"Invalid key","code":"invalid_Key"}'))
        with patch("api.billing.urllib.request.urlopen", side_effect=error), self.assertRaisesRegex(billing.PaystackConfigurationError, "Replace PAYSTACK_SECRET_KEY") as raised:
            billing.initialize_checkout("owner@example.test", "https://desk.test/billing")
        self.assertNotIn("fixturekey", str(raised.exception))
        self.assertNotIn("invalid_Key", str(raised.exception))

    def test_provider_response_never_echoes_secret_keys_into_errors(self):
        body = json.dumps({"message": "Bad sk_test_fixturekey or sk_live_othersecret"}).encode()
        error = urllib.error.HTTPError(billing.PAYSTACK_INIT, 400, "Bad Request", {}, io.BytesIO(body))
        with patch("api.billing.urllib.request.urlopen", side_effect=error), self.assertRaises(RuntimeError) as raised:
            billing._request("/transaction/initialize", {})
        self.assertNotIn("fixturekey", str(raised.exception))
        self.assertNotIn("othersecret", str(raised.exception))

    def test_network_failure_provides_retry_message(self):
        with patch("api.billing.urllib.request.urlopen", side_effect=urllib.error.URLError("fixture network down")), self.assertRaisesRegex(RuntimeError, "Could not connect to Paystack"):
            billing._request("/transaction/initialize", {})

    def test_verify_uses_same_secret_and_encodes_reference(self):
        data = {"status": "success", "amount": 1500000, "reference": "fixture", "customer": {"email": "owner@example.test"}, "metadata": {"plan": "quote-200"}}
        with patch("api.billing.urllib.request.urlopen", return_value=Response({"status": True, "data": data})) as provider:
            result = billing.verify_transaction("fixture/reference?query")
        request = provider.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer sk_test_fixturekey")
        self.assertTrue(request.full_url.endswith("fixture%2Freference%3Fquery"))
        self.assertEqual(result["plan"], "quote-200")

    def test_incomplete_success_response_cannot_open_checkout(self):
        with patch("api.billing.urllib.request.urlopen", return_value=Response({"status": True, "data": {}})), self.assertRaisesRegex(RuntimeError, "checkout link"):
            billing.initialize_checkout("owner@example.test", "https://desk.test/billing")


if __name__ == "__main__": unittest.main()
