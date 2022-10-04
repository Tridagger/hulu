'''
Date: 2022-10-03 15:29:55
Author: Tridagger
Email: san.limeng@qq.com
'''
import os
import time
import sys
import re
from typing import NamedTuple
import asyncio
import json
from functools import wraps
import aiohttp
import aiofiles
from loguru import logger
from settings import BASE_URL, ANIME_LIST_URL, EPISODE_LIST_URL,\
    SOCKS, ONCURRENCY, HEADER, PARAMS, CC_URL_PREFIX, CC_URL_SUFFIX

logger.remove()
logger.add(sys.stdout,
           format="[<yellow>{level}]</yellow><cyan>\
{time:YYYY-MM-DD HH:mm:ss.SSS}</cyan> -> <green>{message}</green>")


class Response(NamedTuple):
    """
    请求返回
    """
    status: int
    text: str


def silence_event_loop_closed(func):
    """
    处理 Windows 系统 RuntimeError('Event loop is closed') 问题
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except RuntimeError as error:
            if str(error) != 'Event loop is closed':
                raise

    return wrapper


class Anime:
    """
    动画
    """

    def __init__(self, name: str, aid: str):
        self.aid: str = aid
        self.name: str = name
        self.seasons: list[Season] = []

    def __repr__(self):
        return self.name


class Season:
    """
    季
    """

    def __init__(self, num: str, anime: Anime):
        self.num: str = num
        self.episodes: list[Episode] = []
        self.of_anime = anime


class Episode:
    """
    集
    """

    def __init__(self, of_season: Season, num: str, title: str, eid: str, cid: str):
        self.num: str = num
        self.eid: str = eid
        self.title: str = title
        self.cid: str = cid
        self.of_season = of_season
        self.of_anime = self.of_season.of_anime


class HuluSubtitleDownloader:
    """
    hulu subtitle 下载器
    """

    def __init__(self, session: aiohttp.ClientSession):
        self.anime_list: list[Anime] = []
        self.session: aiohttp.ClientSession = session
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(ONCURRENCY)
        self.downloaded_cc: list[str] = []
        self.done: dict = {'anime': [], 'episode': []}

    async def __fetch(self, url: str, params: dict | None = None, proxy: str | None = SOCKS)\
            -> Response:
        """
        爬取函数
        """
        async with self.semaphore:
            try:
                logger.info(f'正在爬取：{url}')
                async with self.session.get(url, headers=HEADER, proxy=proxy, params=params)\
                        as response:
                    return Response(response.status, await response.text())
            except aiohttp.ClientProxyConnectionError:
                logger.error(f'请配置代理爬取：{url}')
                sys.exit()

    async def __get_all_anime(self):
        """
        获取所有动画
        """
        res = await self.__fetch(ANIME_LIST_URL, params=PARAMS)
        if res.status == 200:
            raw_text = json.loads(res.text)
            for i in raw_text['items']:
                self.anime_list.append(
                    Anime(name=i['metrics_info']['target_name'], aid=i['id']))
        elif res.status == 403:
            logger.error(f'请使用美国区代理：{ANIME_LIST_URL}')
            sys.exit()
        else:
            logger.error(f'出现错误：{ANIME_LIST_URL}')
            sys.exit()

    async def __get_anime_info(self, anime: Anime):
        """
        获取每部动画详细信息
        """
        url = EPISODE_LIST_URL + anime.aid
        res = await self.__fetch(url, params=PARAMS)
        if res.status == 200:
            raw_text = json.loads(res.text)
            season_info = raw_text['components'][0]['items']
            for i in season_info:
                if ' ' in i['name']:
                    anime.seasons.append(
                        Season(i['name'].split(' ')[-1], anime))
                else:
                    anime.seasons.append(Season('0', anime))
        else:
            logger.error(f'出现错误：{url}')
            sys.exit()

        await asyncio.gather(*(self.__get_episodes(season) for season in anime.seasons))

    async def __get_episodes(self, season: Season):
        url = EPISODE_LIST_URL + season.of_anime.aid + '/season/' + season.num
        res = await self.__fetch(url, params=PARAMS)

        if res.status == 200:
            episodes = json.loads(res.text)['items']

            get_cc_task = []
            for episode in episodes:
                cid: str = episode['personalization']['eab'].split('::')[2]
                eid: str = episode['id']
                title: str = episode['name']
                number: str = episode['number']

                episode = Episode(season, number, title, eid, cid)

                get_cc_task.append(self.__get_cc(episode))

            await asyncio.gather(*get_cc_task)

        else:
            logger.error(f'出现错误：{url}')
            sys.exit()

    async def __get_cc(self, episode: Episode):
        if episode.eid + episode.cid not in self.downloaded_cc:
            # 排除日语版
            if '(Sub)' != episode.title[:5]:
                cc_url = self.__generate_subtitle_url(episode.cid)
                res = await self.__fetch(cc_url, proxy=None)
                if res.status == 200:
                    cc_text = res.text
                    await self.is_cc(episode, cc_text)
                    # 判断字幕是否包含听障文本（CC字幕的特征）
                else:
                    logger.info(f'链接{res.status}：{cc_url}')
            else:
                logger.info(f'{episode.title} 不是英配版，已略过！')
            # 记录此次状态，下次略过
            self.downloaded_cc.append(episode.eid + episode.cid)
        else:
            logger.info(f"已经爬过：{episode.of_anime.name} - {episode.title}")

    async def is_cc(self, episode: Episode, cc_text: str):
        """
        判断字幕是否是 CC 字幕
        """
        if cc_text.count('[') > 10 or cc_text.count('(') > 10 or episode.title[:5] == "(Dub)":
            episode.of_season.episodes.append(episode)
            await self.__save_cc(episode, cc_text)
            self.done['anime'].append(
                episode.of_anime.name + episode.of_season.num)
            self.done['episode'].append(episode.eid)
        else:
            if not os.path.exists('check'):
                os.mkdir('check')
            await self.__save_file(f'check/{self.__fix_name(episode.title)}.vtt', cc_text)
            print(episode.of_anime.name,
                  f'\nS{episode.of_season.num}',
                  f'EP{episode.num}',
                  episode.title)
            if input('\n判断 check 文件夹里的字幕是否是CC字幕(Y/N): ').strip() in ['y', 'Y']:
                episode.of_season.episodes.append(episode)
                await self.__save_cc(episode, cc_text)
                self.done['anime'].append(
                    episode.of_anime.name+episode.of_season.num)
                self.done['episode'].append(episode.eid)
            os.remove(
                f'check/{self.__fix_name(episode.title)}.vtt')

    async def __save_cc(self, episode: Episode, cc_text: str):
        """
        保存字幕
        """
        if not os.path.exists('subtitles'):
            os.mkdir('subtitles/')
        anime_name = self.__fix_name(episode.of_anime.name)
        if episode.of_season.num == '1':
            path = anime_name
        else:
            path = f'{anime_name} S{episode.of_season.num}'
        if not os.path.exists(f'subtitles/{path}'):
            os.mkdir(f'subtitles/{path}')
        file_path = f'subtitles/{path}/{path} - {episode.num}.vtt'
        await self.__save_file(file_path, cc_text)

    @staticmethod
    def __generate_subtitle_url(cid: str) -> str:
        """
        生成字幕下载链接
        """
        small_cid = str(int(cid[-3:]))
        url = f'{CC_URL_PREFIX}{small_cid}/{cid}{CC_URL_SUFFIX}'
        return url

    @staticmethod
    def __fix_name(name: str) -> str:
        """
        使文件名和路径名合法化
        """
        intab = r'[?*/\|:><"]'
        fixed_name = re.sub(intab, "_", name)
        return fixed_name

    async def __get_cookies(self):
        """
        获取 hulu 的 cookies
        """
        await self.__fetch(BASE_URL)

    async def __save_file(self, path: str, text: str):
        """
        保存文件
        """
        async with aiofiles.open(path, 'w', encoding='utf8') as file:
            await file.write(text)

    async def start(self):
        """
        开始爬取
        """
        # 是否需要读取上次爬取信息
        if input('您是否需要读取上次爬取信息？(Y/N): ').strip() in ['y', 'Y']:
            if os.path.exists('archive.json'):
                logger.info("正在读取上次爬取信息")
                with open('archive.json', 'r', encoding='utf8') as file:
                    self.downloaded_cc = json.load(file)
            else:
                logger.warning('archive.json 文件不存在, 将爬取全部字幕！')
                time.sleep(2)
        # 需要访问一次 hulu 网站获得 cookie
        await self.__get_cookies()
        # 获取全部动画名称及动画 id
        await self.__get_all_anime()
        # 获取每部动画的信息并下载字幕
        await asyncio.gather(*(self.__get_anime_info(anime) for anime in self.anime_list))
        # 保存状态
        with open('archive.json', 'w', encoding='utf8') as file:
            json.dump(self.downloaded_cc, file)
        # 输出结果
        anime_done = list(set(self.done['anime']))
        print(f"\n此次共爬取动画{len(anime_done)}部，一共{len(self.done['episode'])}集")
