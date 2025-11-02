# errors/exceptions.py

class DuplicateIDError(Exception):
    def __init__(self):
        super().__init__("Cannot enter both discord_id and jellyfin_id")


class DiscordAlreadyLinkedSameUsername(Exception):
    """Discord ID already registered with this exact username."""
    def __init__(self, username: str):
        self.username = username
        super().__init__(f"Discord user already registered as '{username}'")


class DiscordAlreadyLinkedDifferentUsername(Exception):
    """Discord ID already registered but trying different username."""
    def __init__(self, existing_username: str, requested_username: str):
        self.existing_username = existing_username
        self.requested_username = requested_username
        super().__init__(f"Discord user linked to '{existing_username}', tried '{requested_username}'")


class UsernameExistsUnlinked(Exception):
    """Username exists in Jellyfin but not linked to any Discord."""
    def __init__(self, username: str):
        self.username = username
        super().__init__(f"Username '{username}' exists but unlinked")


class UsernameTaken(Exception):
    """Username is linked to a different Discord user."""
    def __init__(self, username: str):
        self.username = username
        super().__init__(f"Username '{username}' is already taken")