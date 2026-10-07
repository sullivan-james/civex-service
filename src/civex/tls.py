"""What civex trusts when it makes an HTTPS request of its own (sync, the
update check): the same certificates the operating system trusts.

Python's own default doesn't do that everywhere. A Python from python.org on
macOS has no certificates at all until its "Install Certificates" step runs,
and some others carry a fixed list, so a device could fail to reach a server
whose certificate every browser on it accepts ("certificate verify failed:
unable to get local issuer certificate"). `truststore` asks the operating
system instead (Keychain, the Windows certificate store, the system bundle on
Linux): a certificate from a private authority (a company's, or Caddy's
`tls internal`) is trusted once it is added to the system, like in a browser.
"""

from __future__ import annotations

import ssl


def ssl_context() -> ssl.SSLContext:
    """The context every HTTPS request civex makes should use."""
    try:
        import truststore
    except ImportError:  # an install missing it: Python's own default
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def certificate_problem(error: BaseException) -> str | None:
    """Plain words for a failed certificate check, or None when `error`
    isn't one. Says what to do: the usual causes are a server without a
    proper certificate, or one from an authority this computer doesn't
    trust."""
    reason = getattr(error, "reason", error)
    if not isinstance(reason, ssl.SSLCertVerificationError):
        return None
    detail = getattr(reason, "verify_message", None) or str(reason)
    return (
        f"the server's certificate couldn't be checked ({detail}). Use the "
        "server's HTTPS address (a Tailscale address works as it is); if its "
        "certificate comes from a private authority, add that authority to "
        "this computer's trusted certificates"
    )
