from typing import Optional

class RegistrationState:
    def __init__(self):
        self.open = True
        self.max_slots = 0
        self.current = 0

    def reset(self, max_slots: int = 0):
        self.open = True
        self.max_slots = max_slots
        self.current = 0

    def close(self):
        self.open = False

    def increment(self):
        if self.open and not self.is_full() and self.max_slots > 0:
            self.current += 1

    def is_full(self) -> bool:
        return self.max_slots > 0 and self.current >= self.max_slots

    def can_register(self) -> bool:
        return self.open and not self.is_full()

# Singleton instance
registration_state = RegistrationState()
