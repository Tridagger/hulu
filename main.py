import asyncio, aiohttp, os
from asyncio.proactor_events import _ProactorBasePipeTransport as PBPT
from aiosocksy.connector import ProxyConnector, ProxyClientRequest
from tools import Hulu_Subtitle_Downloader, silence_event_loop_closed


async def main():
    async with aiohttp.ClientSession(connector=ProxyConnector(verify_ssl=False), request_class=ProxyClientRequest) as session:

        downloader = Hulu_Subtitle_Downloader(session)
        await downloader.start()

if __name__ == "__main__":
    PBPT.__del__ = silence_event_loop_closed(PBPT.__del__)
    asyncio.run(main())
    os.system('pause')