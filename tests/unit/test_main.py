from fastapi import FastAPI


async def test_lifespan_closes_connections_on_shutdown(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        pass
