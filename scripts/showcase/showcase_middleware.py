"""Visible label applied only by the standalone showcase settings."""

import re


class SyntheticDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            response.get("Content-Type", "").startswith("text/html")
            and not response.streaming
        ):
            raw = response.content.decode(response.charset)
            label = '<div id="synthetic-demo-label" style="position:sticky;top:0;z-index:999999;background:#10262b;color:#d3ffff;border-bottom:2px solid #27b6be;font:600 12px/1.4 system-ui;padding:10px 16px;text-align:center;letter-spacing:.08em">SYNTHETIC DEMO · LOCAL DATA ONLY · NO REAL CUSTOMERS OR PROVIDER CALLS</div>'
            response.content = re.sub(
                r"(<body\b[^>]*>)", lambda m: m[1] + label, raw, count=1, flags=re.I
            )
            response["Content-Length"] = str(len(response.content))
        return response
