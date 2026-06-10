class KeystoneError(Exception):
    pass


class ConfigError(KeystoneError):
    pass


class UnknownTopicError(KeystoneError):
    pass


class UnknownSourceError(KeystoneError):
    pass


class AdapterError(KeystoneError):
    pass


class AuthError(AdapterError):
    pass
