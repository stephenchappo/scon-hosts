"""Run the gateway on both listeners with one app (one ledger, one policy).

machine port: 127.0.0.1:GW_MACHINE_PORT (8640); `tailscale serve` forwards the tailnet here.
cloud port:   127.0.0.1:GW_CLOUD_PORT (8641); only cloudflared forwards here.
"""
import asyncio, os
import uvicorn
from .gateway import create_app


async def main():
    app = create_app()
    servers = [uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(os.environ.get(k, d)),
                                             server_header=False, proxy_headers=False, log_level="info"))
               for k, d in (("GW_MACHINE_PORT", "8640"), ("GW_CLOUD_PORT", "8641"))]
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
