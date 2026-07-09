import base64
import tarfile
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from rag.crosscutting.security.keystore import get_or_create_key


def build_tar(sources: dict[str, Path], output_path: Path) -> Path:
    with tarfile.open(output_path, "w") as tar:
        for arcname, path in sources.items():
            tar.add(path, arcname=arcname)
    return output_path


def extract_tar(tar_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path) as tar:
        tar.extractall(dest_dir, filter="data")


def _backup_fernet(db: Session) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(get_or_create_key(db, "backup")))


def encrypt_archive(db: Session, tar_path: Path, output_path: Path) -> Path:
    output_path.write_bytes(_backup_fernet(db).encrypt(tar_path.read_bytes()))
    return output_path


def decrypt_archive(db: Session, encrypted_path: Path, output_path: Path) -> Path:
    output_path.write_bytes(_backup_fernet(db).decrypt(encrypted_path.read_bytes()))
    return output_path
