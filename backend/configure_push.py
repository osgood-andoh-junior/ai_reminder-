"""Generate local VAPID keys once without printing or replacing existing secrets."""

import argparse
import base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True, help="mailto:contact@example.com or an HTTPS contact URL")
    args = parser.parse_args()
    if not args.subject.startswith(("mailto:", "https://")) or any(c in args.subject for c in "\n\r\"'"):
        parser.error("Use a mailto: or HTTPS contact URI")
    path = Path(__file__).resolve().parent / ".env"
    values = dotenv_values(path) if path.exists() else {}
    keys = ["VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"]
    if any(values.get(k) for k in keys):
        if all(values.get(k) for k in keys):
            print("Existing VAPID configuration preserved. No changes made.")
            return
        parser.error(
            "Partial VAPID configuration exists. Complete it manually; existing values were preserved."
        )
    key = ec.generate_private_key(ec.SECP256R1())
    public = (
        base64.urlsafe_b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )
        .decode()
        .rstrip("=")
    )
    private = (
        base64.urlsafe_b64encode(
            key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        .decode()
        .rstrip("=")
    )
    with path.open("a", encoding="utf-8") as file:
        file.write(
            f"\n# Generated local Web Push configuration\nVAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}\nVAPID_SUBJECT={args.subject}\n"
        )
    print("VAPID keys configured in backend/.env. Existing secrets preserved. Restart API and worker.")


if __name__ == "__main__":
    main()
