from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage


class PrivateEvidenceStorage(FileSystemStorage):
    """Stockage privé : URL interdite et chiffrement symétrique lorsque la clé est configurée."""

    def _fernet(self) -> Fernet | None:
        key = settings.EVIDENCE_ENCRYPTION_KEY.strip()
        if not key:
            return None
        try:
            return Fernet(key.encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ImproperlyConfigured("EVIDENCE_ENCRYPTION_KEY doit être une clé Fernet valide.") from exc

    def _save(self, name: str, content) -> str:
        if settings.AFRIBOUNTY_ENVIRONMENT == "production" and settings.AFRIBOUNTY_EVIDENCE_STORAGE_BACKEND == "private-object":
            raise ImproperlyConfigured("Aucun adaptateur de stockage objet privé n’est encore installé ; l’écriture de preuve est refusée fermement.")
        fernet = self._fernet()
        if fernet is None:
            return super()._save(name, content)
        encrypted = ContentFile(fernet.encrypt(content.read()))
        return super()._save(name, encrypted)

    def _open(self, name: str, mode: str = "rb"):
        stored = super()._open(name, mode)
        fernet = self._fernet()
        if fernet is None:
            return stored
        try:
            decrypted = fernet.decrypt(stored.read())
        except InvalidToken as exc:
            raise ImproperlyConfigured("La preuve chiffrée ne peut pas être déchiffrée avec la clé active.") from exc
        finally:
            stored.close()
        artifact = ContentFile(decrypted)
        artifact.name = name
        return artifact

    def url(self, name: str) -> str:
        raise ValueError("Les preuves ne disposent pas d’URL publique.")


private_evidence_storage = PrivateEvidenceStorage()
