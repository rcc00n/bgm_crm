from __future__ import annotations

from typing import Iterable, Sequence

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape


FONT_STACK = "'Trebuchet MS', 'Lucida Sans Unicode', 'Lucida Grande', Verdana, sans-serif"


def _safe(value: object | None) -> str:
    if value is None:
        return ""
    return escape(str(value))


def _clean_rows(rows: Sequence[tuple[str, object]] | None) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    if not rows:
        return cleaned
    for label, value in rows:
        text = str(value).strip() if value is not None else ""
        if not text:
            continue
        cleaned.append((str(label), text))
    return cleaned


def _clean_items(items: Sequence[tuple[object, object]] | None) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    if not items:
        return cleaned
    for name, qty in items:
        name_text = str(name).strip() if name is not None else ""
        qty_text = str(qty).strip() if qty is not None else ""
        if not name_text and not qty_text:
            continue
        cleaned.append((name_text, qty_text))
    return cleaned


def _format_url(raw: str) -> str:
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"


def build_email_html(
    *,
    title: str,
    preheader: str,
    greeting: str,
    intro_lines: Sequence[str],
    detail_rows: Sequence[tuple[str, object]] | None = None,
    item_rows: Sequence[tuple[object, object]] | None = None,
    summary_rows: Sequence[tuple[str, object]] | None = None,
    notice_title: str | None = None,
    notice_lines: Sequence[str] | None = None,
    footer_lines: Sequence[str] | None = None,
    cta_label: str | None = None,
    cta_url: str | None = None,
) -> str:
    brand_name = _safe(getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors"))
    tagline = _safe(getattr(settings, "SITE_BRAND_TAGLINE", ""))
    address = _safe(getattr(settings, "COMPANY_ADDRESS", ""))
    phone = _safe(getattr(settings, "COMPANY_PHONE", ""))
    website = _safe(getattr(settings, "COMPANY_WEBSITE", ""))
    accent = _safe(getattr(settings, "EMAIL_ACCENT_COLOR", "#d50000"))
    dark = _safe(getattr(settings, "EMAIL_DARK_COLOR", "#0b0b0c"))
    bg = _safe(getattr(settings, "EMAIL_BG_COLOR", "#0b0b0c"))
    company_url = _format_url(getattr(settings, "COMPANY_WEBSITE", "")) or ""

    detail_rows = _clean_rows(detail_rows)
    summary_rows = _clean_rows(summary_rows)
    item_rows = _clean_items(item_rows)

    preheader_html = _safe(preheader)
    title_html = _safe(title)
    greeting_html = _safe(greeting)
    intro_html = "".join(
        f"<p style=\"margin:0 0 12px 0; color:#374151; font-size:14px; line-height:1.6;\">{_safe(line)}</p>"
        for line in intro_lines
        if line
    )

    details_html = ""
    if detail_rows:
        rows_html = "".join(
            "<tr>"
            f"<td style=\"padding:8px 0; color:#6b7280; font-size:11px; letter-spacing:0.18em; "
            f"text-transform:uppercase; width:52%;\">{_safe(label)}</td>"
            f"<td style=\"padding:8px 0; color:#111827; font-size:14px; font-weight:700; text-align:right; "
            f"width:48%;\">{_safe(value)}</td>"
            "</tr>"
            for label, value in detail_rows
        )
        details_html = (
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" "
            "style=\"margin:12px 0 6px 0; border-top:1px solid #e5e7eb; border-bottom:1px solid #e5e7eb;\">"
            f"{rows_html}</table>"
        )

    items_html = ""
    if item_rows:
        rows_html = "".join(
            "<tr>"
            f"<td style=\"padding:10px 0; border-bottom:1px solid #e5e7eb; color:#111827; font-size:14px; "
            f"line-height:1.4;\">{_safe(name)}</td>"
            f"<td style=\"padding:10px 0; border-bottom:1px solid #e5e7eb; color:#111827; font-size:14px; "
            f"font-weight:700; text-align:right; white-space:nowrap;\">{_safe(qty)}</td>"
            "</tr>"
            for name, qty in item_rows
        )
        items_html = (
            "<div style=\"margin-top:18px;\">"
            "<div style=\"color:#6b7280; font-size:11px; font-weight:700; letter-spacing:0.2em; "
            "text-transform:uppercase; margin-bottom:6px;\">Items</div>"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\">"
            f"{rows_html}</table></div>"
        )

    summary_html = ""
    if summary_rows:
        rows_html = "".join(
            "<tr>"
            f"<td style=\"padding:8px 0; color:#e5e7eb; font-size:12px; letter-spacing:0.16em; "
            f"text-transform:uppercase;\">{_safe(label)}</td>"
            f"<td style=\"padding:8px 0; color:#ffffff; font-size:15px; font-weight:800; text-align:right; "
            f"white-space:nowrap;\">{_safe(value)}</td>"
            "</tr>"
            for label, value in summary_rows
        )
        summary_html = (
            f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" "
            f"style=\"margin-top:16px; background:{dark}; border-radius:10px; padding:12px 16px;\">"
            f"{rows_html}</table>"
        )

    notice_html = ""
    notice_lines = [line for line in (notice_lines or []) if line]
    if notice_lines:
        title_label = _safe(notice_title or "Important")
        lines_html = "<br>".join(_safe(line) for line in notice_lines)
        notice_html = (
            f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" "
            f"style=\"margin-top:16px; border:1px solid #e5e7eb; border-left:4px solid {accent}; "
            f"border-radius:8px;\">"
            "<tr><td style=\"padding:12px 14px;\">"
            f"<div style=\"color:#111827; font-size:11px; font-weight:800; letter-spacing:0.2em; "
            f"text-transform:uppercase;\">{title_label}</div>"
            f"<div style=\"margin-top:6px; color:#374151; font-size:14px; line-height:1.5;\">"
            f"{lines_html}</div>"
            "</td></tr></table>"
        )

    footer_note_html = ""
    footer_lines = [line for line in (footer_lines or []) if line]
    if footer_lines:
        lines_html = "<br>".join(_safe(line) for line in footer_lines)
        footer_note_html = (
            "<div style=\"margin-top:18px; color:#4b5563; font-size:13px; line-height:1.6;\">"
            f"{lines_html}</div>"
        )

    cta_html = ""
    if cta_label and (cta_url or company_url):
        href = _format_url(cta_url or company_url)
        cta_html = (
            "<div style=\"margin-top:20px;\">"
            f"<a href=\"{_safe(href)}\" "
            "style=\"display:inline-block; padding:12px 20px; background:"
            f"{accent}; color:#ffffff; text-decoration:none; text-transform:uppercase; "
            "letter-spacing:0.18em; font-size:11px; font-weight:800; border-radius:999px;\">"
            f"{_safe(cta_label)}</a></div>"
        )

    tagline_html = (
        f"<div style=\"color:#9ca3af; font-size:11px; letter-spacing:0.2em; text-transform:uppercase; "
        f"margin-top:6px;\">{tagline}</div>"
        if tagline
        else ""
    )

    contact_lines = []
    if address:
        contact_lines.append(address)
    if phone:
        contact_lines.append(phone)
    if website:
        contact_lines.append(website)
    contact_html = " | ".join(contact_lines)

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title_html}</title>
  </head>
  <body style="margin:0; padding:0; background:{bg};">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">
      {preheader_html}
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{bg};">
      <tr>
        <td align="center" style="padding:26px 16px 10px;">
          <table role="presentation" width="600" cellspacing="0" cellpadding="0"
                 style="width:100%; max-width:600px;">
            <tr>
              <td style="color:#ffffff; font-family:{FONT_STACK}; padding:0 2px 6px;">
                <div style="font-size:22px; font-weight:900; letter-spacing:0.28em; text-transform:uppercase;">
                  {brand_name}
                </div>
                {tagline_html}
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td align="center" style="padding:0 16px 24px;">
          <table role="presentation" width="600" cellspacing="0" cellpadding="0"
                 style="width:100%; max-width:600px; background:#ffffff; border-radius:14px; overflow:hidden;
                        border:1px solid #e5e7eb;">
            <tr>
              <td style="padding:0;">
                <div style="height:4px; background:{accent};"></div>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 32px 24px; font-family:{FONT_STACK};">
                <div style="font-size:18px; font-weight:800; letter-spacing:0.16em; text-transform:uppercase;
                            color:#111827; margin-bottom:10px;">
                  {title_html}
                </div>
                <div style="color:#111827; font-size:14px; font-weight:700; margin-bottom:8px;">
                  {greeting_html}
                </div>
                {intro_html}
                {details_html}
                {notice_html}
                {items_html}
                {summary_html}
                {cta_html}
                {footer_note_html}
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td align="center" style="padding:0 16px 36px;">
          <table role="presentation" width="600" cellspacing="0" cellpadding="0"
                 style="width:100%; max-width:600px;">
            <tr>
              <td style="font-family:{FONT_STACK}; color:#9ca3af; font-size:12px; text-align:center;">
                <div style="font-weight:800; letter-spacing:0.2em; text-transform:uppercase; color:#6b7280;">
                  {brand_name}
                </div>
                <div style="margin-top:6px; line-height:1.6;">{contact_html}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def send_html_email(
    subject: str,
    text_body: str,
    html_body: str,
    *,
    from_email: str,
    recipient_list: Iterable[str],
) -> None:
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=list(recipient_list),
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
