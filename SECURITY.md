# Security

Report a suspected vulnerability privately to **vadrud2016@gmail.com**, with this
repository's name in the subject. This is the maintainer's existing public contact;
no response-time or support guarantee is implied.

Include the affected revision, impact and a minimal reproduction with synthetic
data. Do not include passwords, tokens, customer records, identity documents,
private database URLs or production exports in a public issue or pull request.

Use an isolated local environment for investigation. Obtain explicit permission
before testing a deployed service or an external payment/messaging provider.
If a credential has already been exposed, tell the maintainer privately so it can
be revoked or rotated; removing a line from the current tree does not revoke it.

The checks in this repository have a documented scope. A passing workflow is not a
production security certification or proof that every historical secret was found.
