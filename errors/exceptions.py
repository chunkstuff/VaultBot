# core/exceptions.py

class UserAlreadyExists(Exception):
    """Raised when the Jellyfin user already exists, with optional link status."""
    def __init__(self, username: str, linked: bool = True):
        self.username = username
        self.linked = linked
        link_state = "linked" if linked else "unlinked"
        super().__init__(f"User '{username}' already exists ({link_state})")


class UserLinkedToDifferentDiscord(Exception):
    """Raised when the Jellyfin user exists but is linked to a different Discord ID."""
    def __init__(self, username: str):
        self.username = username
        super().__init__(f"User '{username}' is already linked to a different Discord ID")

class DuplicateIDError(Exception):
    def __init__(self):
        super().__init__("Cannot enter both discord_id and jellyfin_id")
