"""Rerun only relevant existing tests, with real HTTP and SMTP blocked."""
import smtplib
import httpx
import pytest


def denied(*args, **kwargs):
    raise AssertionError("Real HTTP/SMTP disabled during independent acceptance")


httpx.HTTPTransport.handle_request = denied
smtplib.SMTP = denied
smtplib.SMTP_SSL = denied
raise SystemExit(pytest.main([
    "backend/tests/test_v140_real_ai_contract_repairs.py",
    "backend/tests/test_v130_writing_analysis.py",
    "-q", "-p", "no:cacheprovider",
]))
