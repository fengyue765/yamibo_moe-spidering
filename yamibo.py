import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import datetime

VISITED = set()  # 记录已抓取过的帖子URL

def is_valid_url(href):
    if not href:
        return False
    href = href.strip()
    if href.lower().startswith('javascript:'):
        return False
    if href.startswith('#'):
        return False
    if href.lower().startswith('mailto:'):
        return False
    return True

class Logger:
    def __init__(self, logfile="spider_log.txt"):
        self.logfile = logfile
        self.log("========== 爬虫日志开始 ==========")
    def log(self, msg):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{now}] {msg}"
        print(line)
        with open(self.logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")

logger = Logger()

def get_soup(url, session=None):
    session = session or requests.Session()
    resp = session.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, 'html.parser')

def get_louzhu_username(soup):
    for post in soup.find_all('table', class_='plhin'):
        auth_div = post.find('div', class_='authi')
        if auth_div:
            user_link = auth_div.find('a', class_='xw1')
            if user_link:
                return user_link.get_text(strip=True)
    return None

def get_title(soup):
    subject = soup.find('span', id='thread_subject')
    if subject:
        return subject.get_text(strip=True)
    h1 = soup.find('h1', class_='ts')
    if h1:
        return h1.get_text(strip=True)
    title_tag = soup.find('title')
    if title_tag:
        return title_tag.get_text(strip=True)
    return "unknown_title"

def sanitize_folder_name(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()[:60]

def get_all_page_urls(soup, first_url):
    page_urls = set([first_url])
    pgs = soup.find('div', class_='pgs')
    if pgs:
        for a in pgs.find_all('a', href=True):
            href_raw = a['href']
            if not is_valid_url(href_raw):
                continue
            href = urljoin(first_url, href_raw)
            page_urls.add(href)
    return sorted(page_urls)

def get_louzhu_posts(soup, louzhu_name):
    result = []
    for post in soup.find_all('table', class_='plhin'):
        auth_div = post.find('div', class_='authi')
        if not auth_div:
            continue
        user_link = auth_div.find('a', class_='xw1')
        if not user_link:
            continue
        username = user_link.get_text(strip=True)
        louzhu_flag = post.find('em', string='楼主')
        if username == louzhu_name or louzhu_flag:
            msg_td = post.find('td', class_='t_f')
            if msg_td:
                result.append(msg_td)
    return result

def extract_img_urls(post_td, base_url):
    img_urls = set()
    for img in post_td.find_all('img', src=True):
        src = img['src']
        if is_valid_url(src):
            img_urls.add(urljoin(base_url, src))
    for a in post_td.find_all('a', href=True):
        href_raw = a['href']
        if not is_valid_url(href_raw):
            continue
        href = urljoin(base_url, href_raw)
        if re.search(r'\.(jpg|jpeg|png|gif|bmp|webp)$', href, re.I):
            img_urls.add(href)
    return img_urls

def download_imgs(img_urls, save_dir):
    os.makedirs(save_dir, exist_ok=True)
    proxies = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
    }
    for i, url in enumerate(sorted(img_urls), 1):
        try:
            r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'}, proxies=proxies)
            ext = url.split('.')[-1].split('?')[0]
            fname = f'img_{i}.{ext}'
            path = os.path.join(save_dir, fname)
            with open(path, 'wb') as f:
                f.write(r.content)
            logger.log(f"保存图片: {path}")
        except Exception as e:
            logger.log(f"下载失败: {url} 错误: {e}")

def save_louzhu_text(posts, save_dir):
    os.makedirs(save_dir, exist_ok=True)
    out_path = os.path.join(save_dir, "楼主发言.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        for idx, post_td in enumerate(posts, 1):
            text = post_td.get_text('\n', strip=True)
            f.write(f"------ 楼主发言 {idx} ------\n")
            f.write(text)
            f.write("\n\n")
    logger.log(f"保存楼主发言: {out_path}")

def extract_thread_urls(posts, base_url, allowed_domain=None):
    thread_urls = set()
    thread_url_pattern = re.compile(r'thread-\d+-1-1\.html')
    for post_td in posts:
        for a in post_td.find_all('a', href=True):
            href_raw = a['href']
            if not is_valid_url(href_raw):
                continue
            href = urljoin(base_url, href_raw)
            if thread_url_pattern.search(href):
                if allowed_domain is None or urlparse(href).netloc == allowed_domain:
                    thread_urls.add(href)
    return thread_urls

def crawl_thread_recursive(first_page_url, session=None, allowed_domain=None, depth=0, max_depth=3):
    if first_page_url in VISITED:
        return
    VISITED.add(first_page_url)
    indent = "  " * depth
    if depth > max_depth:
        logger.log(f"{indent}[深度超限] 跳过 {first_page_url}")
        return
    logger.log(f"{indent}处理帖子: {first_page_url}")
    try:
        soup = get_soup(first_page_url, session)
        title = get_title(soup)
        folder = sanitize_folder_name(title)
        louzhu_name = get_louzhu_username(soup)
        if not louzhu_name:
            logger.log(f"{indent}楼主用户名识别失败，跳过。")
            return
        page_urls = get_all_page_urls(soup, first_page_url)
        all_img_urls = set()
        all_posts = []
        for p_url in page_urls:
            logger.log(f"{indent}  处理页面: {p_url}")
            psoup = get_soup(p_url, session)
            posts = get_louzhu_posts(psoup, louzhu_name)
            all_posts.extend(posts)
            for post_td in posts:
                all_img_urls.update(extract_img_urls(post_td, p_url))
        logger.log(f"{indent}下载图片与保存发言，总数：图片{len(all_img_urls)}，发言{len(all_posts)}")
        download_imgs(all_img_urls, folder)
        save_louzhu_text(all_posts, folder)
        logger.log(f"{indent}完成: {title} (图片{len(all_img_urls)}，发言{len(all_posts)})")
        # 递归提取新帖子链接
        new_thread_urls = extract_thread_urls(all_posts, first_page_url, allowed_domain)
        for thread_url in new_thread_urls:
            if thread_url not in VISITED:
                crawl_thread_recursive(thread_url, session, allowed_domain, depth+1, max_depth)
    except Exception as e:
        logger.log(f"{indent}处理失败: {first_page_url} 错误: {e}")

def main():
    url_file = 'urls.txt'
    if not os.path.exists(url_file):
        logger.log(f"找不到{url_file}，请创建此文件并填入每个帖子第一页地址（一行一个）")
        return
    with open(url_file, encoding='utf-8') as f:
        url_list = [line.strip() for line in f if line.strip()]
    session = requests.Session()
    allowed_domain = None
    if url_list:
        allowed_domain = urlparse(url_list[0]).netloc
    for url in url_list:
        crawl_thread_recursive(url, session, allowed_domain, depth=0, max_depth=3)
    logger.log("全部递归处理完成。")

if __name__ == "__main__":
    main()