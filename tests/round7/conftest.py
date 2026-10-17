"""Same guard as tests/citizen: no real HTTP request can leave a test."""
from ..citizen.conftest import no_real_http  # noqa: F401
