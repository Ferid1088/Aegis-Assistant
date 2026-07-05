"""Generates strong random values for secrets this appliance needs at install time.

Prints .env-format lines to stdout. Purely a generator — does not read or write any
live config, does not touch docker-compose.yml. install.py calls the same generator
functions this script uses (rag.bootstrap.secrets_gen) to actually write them into
.env during a real install; this script remains useful standalone for an operator who
wants to preview values before installing.
"""

from rag.bootstrap.secrets_gen import (
    generate_jwt_secret, generate_keystore_master_key, generate_neo4j_password, generate_postgres_password,
)


def main():
    print(f"JWT_SECRET_KEY={generate_jwt_secret()}")
    print(f"KEYSTORE_MASTER_KEY={generate_keystore_master_key()}")
    print("# Suggested — not applied automatically. Update docker-compose.yml and .env together:")
    print(f"POSTGRES_PASSWORD={generate_postgres_password()}")
    print(f"NEO4J_PASSWORD={generate_neo4j_password()}")


if __name__ == "__main__":
    main()
