from redis import Redis

from app.db.session import settings

redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_timeout=10,
)