'''
Date: 2022-10-03 15:29:55
Author: Tridagger
Email: san.limeng@qq.com
'''

import os
import asyncio
from asyncio.proactor_events import _ProactorBasePipeTransport as PBPT
import aiohttp
from aiosocksy.connector import ProxyConnector, ProxyClientRequest
from tools import HuluSubtitleDownloader, silence_event_loop_closed


async def main() -> None:
    """
    Main function
    """
    async with aiohttp.ClientSession(connector=ProxyConnector(verify_ssl=False),
                                     request_class=ProxyClientRequest) as session:

        downloader = HuluSubtitleDownloader(session)
        await downloader.start()

if __name__ == "__main__":
    PBPT.__del__ = silence_event_loop_closed(PBPT.__del__)
    asyncio.run(main())
    os.system('pause')
