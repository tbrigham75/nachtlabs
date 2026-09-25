class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def require(condition: bool, status: int, code: str, message: str) -> None:
    if not condition:
        raise DomainError(status, code, message)

