#!/usr/bin/env python3

import os
import gzip
import requests
import xmltodict
from concurrent.futures import ThreadPoolExecutor


DNB_EXPORT_PATH = os.path.sep.join(['dnb_export', ''])
DNB_INDEX_PATH = os.path.sep.join(['dnb_indexes', ''])
DNB_TMP_INDEX_PATH = 'dnb_index.txt'
DNB_SORTED_INDEX_PATH = 'dnb_sorted_index.txt'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36'
BASE_URL = 'https://www.dnb.com/business-directory-sitemapindex.xml'
MAX_WORKERS = 4


def main():
    headers = { 'User-Agent': USER_AGENT }
    res = requests.get(BASE_URL, headers=headers)
    root = xmltodict.parse(res.text)
    locations = [sm["loc"] for sm in root["sitemapindex"]["sitemap"]]

    def get_sitemap_chunk(location):
        if location != 'https://www.dnb.com/sitemap.xml':
            with open(DNB_EXPORT_PATH + location.split('/')[-1], 'wb') as out:
                res = requests.get(location, headers=headers)
                out.write(res.content)

    # Setup index directory
    if not os.path.exists(DNB_INDEX_PATH):
        os.mkdir(DNB_INDEX_PATH)

    # Download the components of sitemap from DNB
    if not os.path.exists(DNB_EXPORT_PATH):
        os.mkdir(DNB_EXPORT_PATH)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor.map(get_sitemap_chunk, locations)

    # Extract all of the company URLs into single index file
    with open(DNB_TMP_INDEX_PATH, 'w') as output_file:
        for filename in os.listdir(DNB_EXPORT_PATH):
            lines = []
            with gzip.open(DNB_EXPORT_PATH + '%s' % filename, 'rb') as nextfile:
                root = xmltodict.parse(nextfile.read())
                # Empty sitemap chunk are returned, not sure why, but it causes
                # issues with parsing.
                try:
                    locations = [url["loc"] for url in root["urlset"]["url"]]
                    lines.extend(map(lambda x: str.strip('.'.join(x.split('.')[3:])) + '\n', locations))
                except:
                    continue
            output_file.writelines(lines)
    
    # The sort command performs more space efficient sorting than what we'd be
    # able to do easily in Python. When you talk about sorting several GBs of
    # data, UNIX tools tend to do it better.
    os.system('sort -fu %s > %s' % (DNB_TMP_INDEX_PATH, DNB_SORTED_INDEX_PATH))
    os.system('rm %s' % DNB_TMP_INDEX_PATH)

    # Partition the sorted index into a set of smaller indexes for faster
    # querying in the general case.
    with open(DNB_SORTED_INDEX_PATH, 'r') as input_file:
        cur_first_char = None
        prev_first_char = None
        current_lines = []

        for rawline in input_file:
            line = rawline.strip()
            if cur_first_char is not None:
                prev_first_char = cur_first_char
            cur_first_char = line[0]
            if prev_first_char is not None and prev_first_char != cur_first_char:
                with open(DNB_INDEX_PATH + 'index_%s.txt' % prev_first_char, 'a') as out:
                    out.writelines(current_lines)
                    current_lines = []
            current_lines.append(line + '\n')

        # Don't forget final "first char"
        with open(DNB_INDEX_PATH + 'index_%s.txt' % prev_first_char, 'a') as out:
            out.writelines(current_lines)

    # Cleanup
    os.system('rm %s' % DNB_SORTED_INDEX_PATH)
    os.system('rm -rf %s' % DNB_EXPORT_PATH)


if __name__ == '__main__':
    main()
