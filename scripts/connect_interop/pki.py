"""TEST-ONLY certificate authority for the interoperability harness.

A fresh CA (and a second, unrelated CA) is generated for every run under the
run directory and is trusted ONLY through each connection's private-CA
setting and the harness driver's explicit ``verify=`` path. Nothing is added
to a system trust store and verification is never disabled. Same approach as
agit8or-connect-public/tools/make_tls_fixtures.py, but with per-run keys.
"""
from __future__ import annotations

import datetime
import ipaddress
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

UTC = datetime.timezone.utc


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _pem(obj) -> bytes:
    if hasattr(obj, 'private_bytes'):
        return obj.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
    return obj.public_bytes(serialization.Encoding.PEM)


def make_ca(cn):
    now = datetime.datetime.now(UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    ku = x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                       key_encipherment=False, data_encipherment=False, key_agreement=False,
                       encipher_only=False, decipher_only=False)
    cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(_name(cn)).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(hours=1)).not_valid_after(now + datetime.timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(ku, critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    return cert, key


def make_leaf(ca, dns_names, ips=('127.0.0.1',)):
    ca_cert, ca_key = ca
    now = datetime.datetime.now(UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    sans = [x509.DNSName(n) for n in dns_names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder().subject_name(_name(dns_names[0])).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(hours=1)).not_valid_after(now + datetime.timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return cert, key


def write(path, data: bytes, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)


def build(pki_dir: str, hosts: dict) -> dict:
    """hosts: {label: dns_name}. Writes ca.pem, other-ca.pem, <label>.crt/.key and
    <label>-other-ca.crt/.key (a certificate for the same name from the other CA)."""
    os.makedirs(pki_dir, mode=0o700, exist_ok=True)
    root = make_ca('Clientst0r interop harness TEST-ONLY CA')
    other = make_ca('Clientst0r interop harness TEST-ONLY unrelated CA')
    out = {'ca': os.path.join(pki_dir, 'ca.pem'), 'other_ca': os.path.join(pki_dir, 'other-ca.pem')}
    write(out['ca'], _pem(root[0]), 0o644)
    write(out['other_ca'], _pem(other[0]), 0o644)
    for label, dns in hosts.items():
        for suffix, issuer in (('', root), ('-other-ca', other)):
            cert, key = make_leaf(issuer, [dns])
            crt, kp = os.path.join(pki_dir, f'{label}{suffix}.crt'), os.path.join(pki_dir, f'{label}{suffix}.key')
            write(crt, _pem(cert), 0o644)
            write(kp, _pem(key))
            out[f'{label}{suffix}'] = (crt, kp)
    return out
