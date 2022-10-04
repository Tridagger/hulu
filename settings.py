'''
Date: 2022-10-04 10:42:37
Author: Tridagger
Email: san.limeng@qq.com
'''

from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini')

BASE_URL = "https://www.hulu.com"
ANIME_LIST_URL = "https://discover.hulu.com/content/v5/view_hubs/anime-tv/collections/4559"
EPISODE_LIST_URL = "https://discover.hulu.com/content/v5/hubs/series/"
SOCKS = config.get('hulu', 'proxy')
ONCURRENCY = int(config.get('hulu', 'concurrency'))
HEADER = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/\
        537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36 Edg/105.0.1343.53'
}
PARAMS = {'schema': '1', 'limit': '9999'}
CC_URL_PREFIX = "https://assetshuluimcom-a.akamaihd.net/captions_webvtt/"
CC_URL_SUFFIX = "_US_en_en.vtt"
