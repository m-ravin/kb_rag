"""Central slowapi rate limiter — import this singleton in routers that need it."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
