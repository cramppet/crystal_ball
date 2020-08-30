#!/usr/bin/env python3

import os
import csv
import sys
import json
import argparse
import urllib.request
import tarfile
import requests
import tldextract

from urllib.parse import urlencode, urlparse
from beautifultable import BeautifulTable


CRUNCHBASE_ODM = {}
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36';
WIKIDATA_QUERY = '''
SELECT DISTINCT ?item ?itemLabel ?url WHERE {
  {
    SELECT ?item WHERE { ?item (wdt:P31/wdt:P279*) wd:Q43229. }
  }
  ?item (wdt:P127|^wdt:P199|wdt:P749|^wdt:P1830|^wdt:P355)+ wd:QXXX.
  OPTIONAL{?item wdt:P856 ?url .}
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
}
'''.replace('\n', ' ').replace('\t', ' ')


def load_crunchbase_odm():
    if os.path.exists('organizations.csv'):
        with open('organizations.csv', 'r') as odm_file:
            odm_reader = csv.reader(odm_file)
            for row in odm_reader:
                CRUNCHBASE_ODM[row[1]] = row[5]
    else:
        sys.stderr.write('Error, could not load "organizations.csv"')


def download_crunchbase_odm(odm_key):
    ODM_URL = 'https://api.crunchbase.com/odm/v4/odm.tar.gz?user_key=%s' % odm_key
    file_stream = urllib.request.urlopen(ODM_URL)
    file_handle = tarfile.open(fileobj=file_stream, mode="r|gz")
    file_handle.extractall()
    os.system('rm checksum.csv people.csv')


def read_config():
    if os.path.exists('config.json'):
        with open('config.json', 'r') as config_file:
            return json.loads(config_file.read())
    else:
        sys.stderr.write('Error, could not load "config.json"')
    return None


def extract_domain(value):
    if len(value) > 0:
        x = urlparse(value).netloc
        t = tldextract.extract(x)
        return t.domain + '.' + t.suffix
    return value


def cw_get_company_by_name(name):
    base = "http://api.corpwatch.org/companies.json?"
    cw_id = None
    transformed_name = urlencode({ 'company_name': name.lower() })
    res = requests.get(base + transformed_name)
    root = json.loads(res.text)
    if 'companies' in root['result']:
        companies = root['result']['companies']
        all_cw_ids = [companies[c]['top_parent_id'] for c in companies]
        # Find the parent id which occurs the most frequently.
        cw_id = sorted(map(lambda id: (id, all_cw_ids.count(id)),
                           list(set(all_cw_ids))), 
                       key=lambda tup: tup[1])[-1][0]
    return cw_id


def cw_get_child_companies(cw_id):
    base = "http://api.corpwatch.org/companies.json?top_parent_id="
    child_companies = None
    res = requests.get(base + cw_id)
    root = json.loads(res.text)
    all_c = root['result']['companies']
    child_companies = [all_c[c]['company_name'] for c in all_c]
    return child_companies


def clearbit_resolve(name, clearbit_key):
    base = 'https://company.clearbit.com/v1/domains/find?'
    args = urlencode({ 'name': name.lower() })
    res = requests.get(base + args, auth=(clearbit_key, ''))
    body = json.loads(res.text)
    return body['domain'] if 'domain' in body else ''


def knowledge_graph_resolve(name, kg_api_key):
    base = 'https://kgsearch.googleapis.com/v1/entities:search?'
    args = urlencode({'query': name.lower(), 'key': kg_api_key, 'limit': '1'})
    res = requests.get(base + args)
    body = json.loads(res.text)
    if not 'itemListElement' in body:
        return ''
    if len(body['itemListElement']) == 0:
        return ''
    return body['itemListElement'][0]['result']['url']


def wikidata_resolve(wikidata_id):
    base = 'https://query.wikidata.org/sparql?'
    query = WIKIDATA_QUERY.replace('QXXX', wikidata_id)
    args = urlencode({'format': 'json', 'query': query})
    headers = { 'User-Agent': USER_AGENT }
    res = requests.get(base + args, headers=headers)
    body = json.loads(res.text)
    ret = []
    for e in body['results']['bindings']:
        name = e['itemLabel']['value']
        domain = ''
        if 'url' in e and e['url']:
            domain = extract_domain(e['url']['value'])
        ret.append([name, domain, 'WikiData'])
    return ret


def try_resolve_names(names, config):
    res = []
    for name in names:
        if name in CRUNCHBASE_ODM:
            res.append([name, CRUNCHBASE_ODM[name], 'Crunchbase'])
        else:
            resolved = clearbit_resolve(name, config['clearbit_key'])
            if len(resolved) == 0:
                resolved = knowledge_graph_resolve(name, config['google_api_key'])
                if len(resolved) != 0:
                    res.append([name, extract_domain(resolved), 'Google'])
                else:
                    res.append([name, '', ''])
            else:
                res.append([name, resolved, 'Clearbit'])
    return res


def main():
    parser = argparse.ArgumentParser(description='Attempt to locate subsidiaries of an organization')
    parser.add_argument('-c', metavar='COMPANY', required=False, help='Canonical company name')
    parser.add_argument('-w', metavar='ID', required=False, help='WikiData entity ID')
    parser.add_argument('-i', metavar='INPUT', required=False, help='Supplemental input file of subsidiaries')
    parser.add_argument('-o', metavar='OUTPUT', required=False, help='Output file location')

    args = parser.parse_args()
    config = read_config()
    table = BeautifulTable()
    table.column_headers = ['Name', 'Domain', 'Source']
    subsidiaries = []

    if not os.path.exists('organizations.csv'):
        download_crunchbase_odm(config['crunchbase_odm_key'])

    load_crunchbase_odm()

    if args.c is not None:
        company = args.c
        cw_id = cw_get_company_by_name(company)
        if cw_id is not None:
            subsidiaries.extend(cw_get_child_companies(cw_id))

    if args.w is not None:
        wikidata_id = args.w
        for row in wikidata_resolve(wikidata_id):
            table.append_row(row)
    
    if args.i is not None:
        with open(args.i, 'r') as input_file:
            subsidiaries.extend(map(str.strip, input_file.readlines()))

    for row in try_resolve_names(subsidiaries, config):
        table.append_row(row)

    if args.o is not None:
        with open(args.o, 'w') as output_file:
            output_writer = csv.writer(output_file, quoting=csv.QUOTE_MINIMAL)
            for row in table:
                output_writer.writerow(list(row))

    if len(table) == 0:
        sys.stderr.write('[-] Error, no subsidiaries identified for "%s"\n' % company)

    print(table)


if __name__ == '__main__':
    main()
