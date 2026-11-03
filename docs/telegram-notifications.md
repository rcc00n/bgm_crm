# Telegram notifications

Public forms save valid inquiries before content review. Heuristic concerns keep
the inquiry and send a prompt staff alert; known phishing campaign indicators
send it to **Lead review queue**, with a scheduled summary. Nothing is deleted.
Staff can release an inquiry or mark it as spam; both decisions retain its source.
Only invalid form tokens and honeypot hits are rejected without an inquiry.

Lead summaries run at 15:00 and 21:00 in `America/Edmonton`. They combine form
types and label blocked attempts separately from saved requests awaiting review.
Aggregation uses bounded Redis counters, not queries over submission history.
Empty windows do not send a message. The existing Telegram bot runs the scheduler
once a minute; no extra worker or cron container is needed.

`LEAD_REDIS_URL` configures the shared Django `lead_security` cache. Keep it private
in Dokku configuration. Security counters and one-use token protection share this
connection. A Redis outage leaves valid customer intake working and sends a safe
fallback alert for a quarantined inquiry when its summary cannot be queued.

Outbound messages are saved before the Telegram API call. The delivery journal
records the source entity, deduplication key, Telegram message ID and retry state.
Each recipient is claimed separately; successful recipients are not sent the same
event again. Failed sends retry with bounded backoff. A transport timeout is marked
**uncertain**: Telegram does not offer an idempotency key, so a retry after an
ambiguous timeout can repeat that particular delivery.

The bot also processes enabled daily operations reports and scheduled reminders.
`TELEGRAM_AUTOMATION_START_AT` is the rollout cutoff for automatic reminder
processing, to avoid unexpectedly replaying old pending reminders. Older reminders
remain visible and can be explicitly sent from the admin.

Use **Telegram message logs** for delivery status and **Lead review queue** for
saved inquiries. The queue links to the complete original request. Known campaign
domains are neutralized in Telegram text. Ordinary customer document links are
allowed; no external reputation API or model call runs during form submission.

Regression checks include real PostgreSQL migrations, customer form submissions,
delivery retries and real Redis Lua concurrency tests. The Redis checks use a
random namespace and delete only their own keys:

```sh
LEAD_DIGEST_TEST_REDIS_URL=redis://127.0.0.1:16391/0 \
  python manage.py test notifications.test_lead_digest
```
