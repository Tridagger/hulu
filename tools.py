import re, asyncio, logging, aiohttp, aiofiles, json, os, configparser
from typing import Any, Coroutine, Tuple
from functools import wraps
from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini')

# 参数设定
BASE_URL = "https://www.hulu.com"
ANIME_LIST_URL = "https://discover.hulu.com/content/v5/view_hubs/anime-tv/collections/4559"
EPISODE_LIST_URL = "https://discover.hulu.com/content/v5/hubs/series/"
SOCKS = config.get('hulu','proxy')
ONCURRENCY = int(config.get('hulu','concurrency'))
HEADER = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36 Edg/105.0.1343.53'
}
PARAMS = {'schema': '1', 'limit': '9999'}


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')


def silence_event_loop_closed(func):
    """
    处理 Windows 系统 RuntimeError('Event loop is closed') 问题
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except RuntimeError as e:
            if str(e) != 'Event loop is closed':
                raise

    return wrapper


class Anime:
    """
    动画
    """

    def __init__(self, name: str, id: str):
        self.id: str = id
        self.name: str = name
        self.seasons: list[Season] = []

    def __repr__(self):
        return self.name


class Season:
    """
    季
    """

    def __init__(self, num: str):
        self.num: str = num
        self.episodes: list[Episode] = []

class Episode:
    """
    集
    """

    def __init__(self, num: str, title: str, id: str, cc_id: str):
        self.num: str = num
        self.id: str = id
        self.title: str = title
        self.cc_id: str = cc_id


class Hulu_Subtitle_Downloader:

    def __init__(self, session: aiohttp.ClientSession):
        self.anime_list: list[Anime] = []
        self.session: aiohttp.ClientSession = session
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(ONCURRENCY)
        self.downloaded_cc: list[str] = []
        self.done: dict = {'anime': [], 'episode': []}

    async def __fetch(self, url: str, params: dict = {}, proxy: str = SOCKS) -> Tuple[int, Coroutine[Any, Any, str | None]]:
        """
        爬取函数
        """
        async with self.semaphore:
            try:
                logging.info(f'正在爬取：{url}')
                async with self.session.get(url, headers=HEADER, proxy=proxy, params=params) as response:
                    return response.status, await response.text()
            except aiohttp.client_exceptions.ClientProxyConnectionError:
                logging.error(f'请配置代理爬取：{url}')
                exit()

    async def __get_all_anime(self):
        """
        获取所有动画
        """
        res = await self.__fetch(ANIME_LIST_URL, params=PARAMS)
        if res[0] == 200:
            raw_text = json.loads(res[1])
            for i in raw_text['items']:
                self.anime_list.append(
                    Anime(name=i['metrics_info']['target_name'], id=i['id']))
        elif res[0] == 403:
            logging.error(f'请使用美国区代理：{ANIME_LIST_URL}')
            exit()
        else:
            logging.error(f'出现错误：{ANIME_LIST_URL}')
            exit()

    async def __get_anime_info(self, anime: Anime):
        """
        获取每部动画详细信息
        """
        url = EPISODE_LIST_URL + anime.id
        res = await self.__fetch(url, params=PARAMS)
        if res[0] == 200:
            raw_text = json.loads(res[1])
            season_info = raw_text['components'][0]['items']
            for i in season_info:
                if ' ' in i['name']:
                    anime.seasons.append(Season(i['name'].split(' ')[-1]))
                else:
                    anime.seasons.append(Season('0'))
        else:
            logging.error(f'出现错误：{url}')
            exit()

        await asyncio.gather(*(self.__get_episodes(anime, season) for season in anime.seasons))

    async def __get_episodes(self, anime: Anime, season: Season):
        url = EPISODE_LIST_URL + anime.id + '/season/' + season.num
        res = await self.__fetch(url, params=PARAMS)

        if res[0] == 200:
            episodes = json.loads(res[1])['items']

            get_cc_task = []
            for ep in episodes:
                cc_id: str = ep['personalization']['eab'].split('::')[2]
                ep_id: str = ep['id']
                name: str = ep['name']
                number: str = ep['number']

                get_cc_task.append(self.__get_cc(number, name, ep_id, cc_id ,ep, season, anime))

            await asyncio.gather(*get_cc_task)
                
        else:
            logging.error(f'出现错误：{url}')
            exit()

    async def __get_cc(self, number: str, name: str, ep_id:str, cc_id: str ,ep: dict, season: Season, anime: Anime):
        if ep_id + cc_id not in self.downloaded_cc:
            # 排除日语版
            if '(Sub)' != ep['name'][:5]:
                episode = Episode(number, name, ep_id, cc_id)
                cc_url = self.__generate_subtitle_url(episode.cc_id)
                res = await self.__fetch(cc_url, proxy=None)
                if res[0] == 200:
                    cc_text: str = res[1]
                    # 判断字幕是否包含听障文本（CC字幕的特征）
                    if cc_text.count('[') > 10 or cc_text.count('(') > 10 or episode.title[:5] == "(Dub)":
                        season.episodes.append(episode)
                        await self.__save_cc(anime, season, episode, cc_text)
                        self.done['anime'].append(anime.name+season.num)
                        self.done['episode'].append(episode.id)
                    else:
                        if not os.path.exists(f'check'):
                            os.mkdir(f'check')
                        with open(f'check/{self.__fix_name(episode.title)}.vtt', 'w', encoding='utf8') as f:
                            f.write(cc_text)
                        print(
                            anime.name, f'\nS{season.num}', f'EP{episode.num}', episode.title)
                        if input('\n判断 check 文件夹里的字幕是否是CC字幕(Y/N): ').strip() in ['y', 'Y']:
                            season.episodes.append(episode)
                            await self.__save_cc(anime, season, episode, cc_text)
                            self.done['anime'].append(
                                anime.name+season.num)
                            self.done['episode'].append(episode.id)
                        os.remove(
                            f'check/{self.__fix_name(episode.title)}.vtt')

                elif res[0] == 404:
                    logging.info(
                        f'链接404：{cc_url}')

            # 记录此次状态，下次略过
            self.downloaded_cc.append(ep_id + cc_id)
        else:
            logging.info(f"已经爬过：{anime.name} - {name}")

    async def __save_cc(self, anime: Anime, season: Season, ep: Episode, cc_text: str):
        """
        保存字幕
        """
        if not os.path.exists(f'subtitles'):
            os.mkdir(f'subtitles/')
        anime_name = self.__fix_name(anime.name)
        if season.num == '1':
            path = anime_name
        else:
            path = f'{anime_name} S{season.num}'
        if not os.path.exists(f'subtitles/{path}'):
            os.mkdir(f'subtitles/{path}')
        async with aiofiles.open(f'subtitles/{path}/{path} - {ep.num}.vtt', 'w+', encoding='utf8') as f:
            await f.write(cc_text)

    @staticmethod
    def __generate_subtitle_url(sub_id: str) -> str:
        """
        生成字幕下载链接
        """
        small_id = str(int(sub_id[-3:]))
        url = f'https://assetshuluimcom-a.akamaihd.net/captions_webvtt/{small_id}/{sub_id}_US_en_en.vtt'
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
        await self.__fetch('https://www.hulu.com')

    async def start(self):
        """
        开始爬取
        """
        # 是否是第一次爬取
        if input('您是否是第一次爬取 HULU 的 CC 字幕(Y/N): ').strip() in ['y', 'Y']:
            if os.path.exists('downloaded_cc.json'):
                os.remove('downloaded_cc.json')
        # 读取上次状态
        if os.path.exists('downloaded_cc.json'):
            logging.info("正在读取上次爬取信息")
            with open('downloaded_cc.json', 'r') as f:
                self.downloaded_cc = json.load(f)

        # 需要访问一次 hulu 网站获得 cookie
        await self.__get_cookies()
        # 获取全部动画名称及动画 id
        await self.__get_all_anime()
        # 获取每部动画的信息并下载字幕
        await asyncio.gather(*(self.__get_anime_info(anime) for anime in self.anime_list))
        # 保存状态
        with open('downloaded_cc.json', 'w') as f:
            json.dump(self.downloaded_cc, f)
        # 输出结果
        anime_done = list(set(self.done['anime']))
        print(f"\n此次共爬取动画{len(anime_done)}部，一共{len(self.done['episode'])}集")