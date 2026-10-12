from __future__ import annotations

import keyring

SERVICE_NAME = "CampusNet Auto Login"
USERNAME_KEY = "portal-username"
PASSWORD_KEY = "portal-password"


class CredentialError(RuntimeError):
    """Raised when the OS credential manager cannot safely store or retrieve secrets."""


def save_credentials(username: str, password: str) -> None:
    if not username.strip() or not password:
        raise ValueError("Username and password cannot be empty.")
    try:
        keyring.set_password(SERVICE_NAME, USERNAME_KEY, username.strip())
        keyring.set_password(SERVICE_NAME, PASSWORD_KEY, password)
        # Read-back checks that the selected backend actually persisted the data.
        if keyring.get_password(SERVICE_NAME, USERNAME_KEY) != username.strip():
            raise CredentialError("Could not verify the saved username in the OS credential store.")
        if keyring.get_password(SERVICE_NAME, PASSWORD_KEY) != password:
            raise CredentialError("Could not verify the saved password in the OS credential store.")
    except CredentialError:
        raise
    except Exception as exc:
        raise CredentialError(
            "Could not access the OS credential store. Configure a supported keyring backend; "
            "CampusNet will not save credentials as plain text."
        ) from exc


def load_credentials() -> tuple[str, str]:
    try:
        username = keyring.get_password(SERVICE_NAME, USERNAME_KEY)
        password = keyring.get_password(SERVICE_NAME, PASSWORD_KEY)
    except Exception as exc:
        raise CredentialError("Could not read credentials from the OS credential store.") from exc
    if not username or not password:
        raise CredentialError("No saved credentials. Run `campusnet setup` first.")
    return username, password


def delete_credentials() -> None:
    errors: list[Exception] = []
    for key in (USERNAME_KEY, PASSWORD_KEY):
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise CredentialError("Could not delete one or more credentials from the OS credential store.") from errors[0]
