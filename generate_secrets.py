"""Generates strong random values for secrets this appliance needs at install time.

Prints .env-format lines to stdout. Purely a generator — does not read or write any
live config, does not touch docker-compose.yml. The phase 8.5 installer will call
this and wire the output in; today it's a standalone tool.
"""

import secrets

from cryptography.fernet import Fernet


def main():
    print(f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"KEYSTORE_MASTER_KEY={Fernet.generate_key().decode()}")
    print("# Suggested — not applied automatically. Update docker-compose.yml and .env together:")
    print(f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}")
    print(f"NEO4J_PASSWORD={secrets.token_urlsafe(24)}")


if __name__ == "__main__":
    main()
