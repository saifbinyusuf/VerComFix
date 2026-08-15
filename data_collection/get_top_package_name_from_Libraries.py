import os
import time
import random

from bs4 import BeautifulSoup

import requests
from pathlib import Path
base_time = 30  # Base wait time
variation = 10  # Max fluctuation range

def _make_request(url, retries=3, timeout=10, header=1):
        headers1 = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                   "Cookie": "drift_aid=df6ba3b0-2c4d-4f85-9493-79397e9019ae; driftt_aid=df6ba3b0-2c4d-4f85-9493-79397e9019ae; _ga=GA1.1.1516911730.1746514999; _ga_F1CSL7HJCK=GS2.1.s1746593129$o8$g0$t1746593130$j59$l0$h0; _libraries_session=QkewmGmS6IoNNH%2BOLti%2FJp8ceClqA7QYWj0ztd7ZUQ3%2FjXWSGcXB4aMwFKuIpKFVfhZN0iaCTyQk2BzTSCZckU%2BvVtvg7pn2RSe4T%2FQCvJeYw0yf0Di%2FEoTu3M12D%2BCaXuDilBfjz%2BXlCxWuwd6gV11r%2BumrX4Ii6ZPX6XR38LDRXmN%2BTQ2gfUvOHyVuZBBpoUQRbqVHPZQVw7h9kbmzI36UUXbJYinC60JgYMgifTwH9mR12JudB0R3DNJP7Ki87l8ccTlfb02o664CnGwej4ycjfNVKnYCdSuB7CKABri4UovZy5xZX6da98qXdrWd0QVXQ%2FfdlbmCQ%2FXIqgmnqQCJ5s0%3D--uyOphPB67SSmaip8--xgH2qNALXHP1n2xbDJmaGA%3D%3D"
                   }
        headers2 = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                   "Cookie": "_gid=GA1.2.671179132.1746514999; drift_aid=df6ba3b0-2c4d-4f85-9493-79397e9019ae; driftt_aid=df6ba3b0-2c4d-4f85-9493-79397e9019ae; _libraries_session=GxPxGQGlhuxOvKzLYv4dkrxjn4VOGU2ytQ7Fa1abc%2FgjeJ%2BNPwFw2s3jV%2FqwfBRcbXMRtLHoVEvNAMRfV5lpeYSoN4uhb7M5HGDpoPOwguRGLCgFs15mSuGX%2FLCxip4pPNxKo%2FSGqfduaLCcxeyD9K1H461KKMvE3q4vSVYNsPGXbFFcF1OQUZIo01F7dGcnOYAmWHcwFZvEMuMO2VFJRFgg2dbrIi4gHXB%2BTKqjogpNwXECPy%2Bzesy%2BtwMZt6%2Fny9BOEzfyaLMMqzo205Uht448foXemNQmPSc74N5b6ACAHcdo1ZQsLdV4lAms8N3pVpPNoWLNW9XYAoBiu7mrXSa%2FAUk%3D--WcYRS7BmnZOiGAwQ--Shl%2FVOy%2BvrdlCgbytHyKnw%3D%3D; _ga_F1CSL7HJCK=GS2.1.s1746544562$o7$g1$t1746544858$j60$l0$h0; _ga=GA1.1.1516911730.1746514999; _gat=1"
                   }
        headers3 = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                   "Cookie": "_gid=GA1.2.671179132.1746514999; drift_aid=df6ba3b0-2c4d-4f85-9493-79397e9019ae; driftt_aid=df6ba3b0-2c4d-4f85-9493-79397e9019ae; _gat=1; _libraries_session=hUiquBdr7iIpVk9H0Ong5njqSVVwIesQyGcqo04UZcysy6oAd1ro4H7o2hN%2BZ0rpgikuyzEh20g0ACIONYtbCGeAPgGwxFRZSiVjEQgPJ8TOndeb3SfpSs9r6eTFd%2FtvbeQGDCWqp0Xwn%2FaL4ZGPqflmViws%2BR7vO80%2Bd0cb%2F7fEcg1w72QePNxr4bs2eyM4yo1xWpFW33RxED07SeAHjNYT09ckZ4BfVFxof9Mwn70lM5NI%2FYI9tBcSGs97f5hYzA0VIBf3YztlmR6n2D7lmW2D55HXUFkGrjPcRzCJoBwgsblqdD4lufSwshtp%2BKTqez1qLFaLKJCI%2BcnwtCvqZhnuvTY%3D--Iwd29vkEhCRaNgyc--9yOs5KPTMGYASFpzXle%2F0w%3D%3D; _ga_F1CSL7HJCK=GS2.1.s1746544562$o7$g1$t1746545012$j60$l0$h0; _ga=GA1.1.1516911730.1746514999"
                   }
        headers4 = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                   "Cookie": "_libraries_session=yc5Py9cTBJUgkPrqOlHzfgsQyCosPS%2BUdhbHXAOY8OQCnt5uQeknguU4aP89ZsyhPKt0Yiqh3fbux13dLg9G0OG%2FfI4YmeC0CvxQuk%2B6tNRXReSXJrdzrjb3FSJ4EITVdNDKdP3rFZH%2FUZbTQkZ0Sa4kYTnZoyfq6J87caIbiFKNOEczQpm7bJC21a5UNnC78C1CAiXbtx4q7FE5pI0qyr2k9czw5VoDf9W7ZAS0uIiBl7F8hoMFRh7wDRB%2FO4ETbPKB%2B5cLtgiLpJHgEjoS6zzvpoC%2B%2FlQVVc5e1N2L0axFc4Jn%2BILnmx3X9kzFTobu6s7d3GRtyuxIvXELVj%2FY8PskCsk%3D--d3AYyXj1LW1%2Bj%2FOH--GZD5X2e9BVx2idoqhsJ8pQ%3D%3D"
                   }
        proxies = {
            "http": "http://127.0.0.1:7890",
            "https": "http://127.0.0.1:7890"
        }
        for attempt in range(retries):
            try:
                if header == 4:
                    response = requests.get(url,headers=headers4,timeout=timeout)
                elif header == 3:
                    response = requests.get(url,headers=headers3,timeout=timeout)
                elif header == 2:
                    response = requests.get(url,headers=headers2,timeout=timeout)
                else :
                    response = requests.get(url,headers=headers1,timeout=timeout)
                return response
            except requests.exceptions.RequestException as e:
                print(f"Request exception: {e}, retrying {attempt + 1}/{retries}")
        
        # If all retries fail, return None or raise exception
        print(f"Request failed, reached max retries: {retries}, URL: {url}")
        return None

def write_to_file(file, context, write_type):
    try:
        file = open(file, write_type)
        file.write(context)
        file.write('\n')
    finally:
        file.close()


def top_package_name():
    rank = 1
    for i in range(1, 401):
        url = "https://libraries.io/search?order=desc&page=%s&platforms=PyPI&sort=dependent_repos_count" % i
        print(url)
        # r = requests.get(url)
        r = _make_request(url, header=1)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            all_projects = soup.find_all('div', class_='project')
            if not all_projects:
                print('No more data')
                return
            for project in all_projects:
                if rank > 10000:
                # if rank > 3:
                    return
                write_to_file('./rank.txt', '%s@@%s' % (str(rank), project.find('a').text), 'a')
                rank += 1
        else:
            print('Page %s' % i)
            return

        sleep_time = random.uniform(base_time - variation, base_time + variation)
        print(f'Sleeping for {sleep_time:.2f} seconds')
        time.sleep(sleep_time)


if __name__ == '__main__':
    current_folder = Path(__file__).resolve().parent
    top_package_name()
