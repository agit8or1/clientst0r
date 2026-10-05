# Security review — 2026-10-02

## Changes

- Secret reveal, OTP and QR endpoints enforce vault_view_password on the target organization, including staff global role templates. Permissions in an unrelated organization do not grant create/edit access. Personal secrets require their owner.
- Mobile reveal returns 503 on policy-evaluation errors instead of releasing a password. Missing allow decisions are denied. OTP/QR paths enforce the same access policy.
- Resolve client addresses only through explicitly trusted proxy peers, walking X-Forwarded-For from the nearest proxy backwards. Malformed chains fail closed; a caller-controlled prefix cannot become a loopback firewall bypass.
- The bundled single-edge Nginx templates overwrite X-Forwarded-For with the peer address. Forwarded private addresses must follow configured firewall policy.

## Validation

```sh
python -m unittest discover -s security_tests -v
```

16 offline regression tests cover real permission/address helpers and isolated handler bodies with database doubles. Full Django/MySQL integration, mobile device behavior and deployed reverse-proxy topology were not exercised.

## Rollout

Set TRUSTED_PROXY_CIDRS to the exact reverse proxy addresses/CIDRs; the default trusts only 127.0.0.1/32 and ::1/128. For Nginx on the same server, that default is appropriate. With an external load balancer or container network, specify the actual proxy addresses and configure each trusted hop to append or overwrite forwarding headers correctly. Do not trust 0.0.0.0/0 or ::/0. The bundled Nginx snippets assume a single public edge; adapt multiple-hop deployments deliberately.

Before restart, check that enabled IP allowlists include the administrator's real source address. Forwarded private addresses no longer receive an unconditional LAN bypass. Assign the intended global role template to staff accounts; staff status alone no longer grants secret access. Superusers retain organization-wide access but do not gain access to another user's personal vault. No schema migration is required.

Python dependency ranges were inspected but were not resolved into a complete deployed dependency inventory. Run pip-audit in the deployment's actual virtual environment as a separate gate.
