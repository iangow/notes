#!/usr/bin/env python3
"""Inspect alternative public files for selected unavailable audit references."""

import argparse
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

import duckdb

from benchmark_sgml_block_sampling import DEFAULT_USER_AGENT


def probe(url):
    status=None
    prefix=None
    acceptance=None
    error=None
    content_type=None
    try:
        request=urllib.request.Request(url,headers={'User-Agent':DEFAULT_USER_AGENT,'Accept-Encoding':'identity'})
        with urllib.request.urlopen(request,timeout=30) as response:
            status=response.status
            content_type=response.headers.get('Content-Type')
            prefix=response.read(256*1024)
        text=prefix.decode('latin-1')
        if match:=re.search(r'<ACCEPTANCE-DATETIME>\s*(\d{14})',text):
            acceptance=datetime.strptime(match[1],'%Y%m%d%H%M%S')
    except Exception as exc:
        status=exc.code if isinstance(exc,urllib.error.HTTPError) else status
        error=f'{type(exc).__name__}: {exc}'
    return status,content_type,acceptance,prefix,error


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.report),read_only=True) as source,duckdb.connect() as con:
        rows=source.execute('''WITH selected AS (
            SELECT DISTINCT cik,accessionNumber,raw_clock,error FROM outcomes WHERE NOT verifiable
        ) SELECT * FROM selected WHERE raw_clock>=TIMESTAMP '2003-01-01'
            OR CAST(raw_clock AS TIME) NOT IN (TIME '00:00:00',TIME '04:00:00',TIME '05:00:00')
        UNION SELECT * FROM selected ORDER BY raw_clock LIMIT 3''').fetchall()
        # Select controls separately so the LIMIT does not trim the main groups.
        rows=source.execute('''SELECT DISTINCT cik,accessionNumber,raw_clock,error FROM outcomes
            WHERE NOT verifiable AND (raw_clock>=TIMESTAMP '2003-01-01'
            OR CAST(raw_clock AS TIME) NOT IN (TIME '00:00:00',TIME '04:00:00',TIME '05:00:00'))''').fetchall()+rows
        rows=list({(r[0],r[1]):r for r in rows}.values())
        con.execute('''CREATE TABLE probes(cik BIGINT,accession_number VARCHAR,raw_clock TIMESTAMP,
            kind VARCHAR,url VARCHAR,retrieved_at TIMESTAMPTZ,http_status INTEGER,content_type VARCHAR,
            acceptance_datetime TIMESTAMP,response_prefix BLOB,prefix_sha256 VARCHAR,error VARCHAR)''')
        for cik,accession,clock,_ in rows:
            urls=[('complete_submission',f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt')]
            if accession.startswith('9999999997-') and clock.year>=2025:
                paper=accession[11:13]+accession[-6:]
                urls.append(('paper_pdf',f'https://www.sec.gov/Archives/edgar/vprr/{paper[:4]}/{paper}.pdf'))
            for kind,url in urls:
                time.sleep(.15)
                status,content_type,acceptance,prefix,error=probe(url)
                con.execute('INSERT INTO probes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    [cik,accession,clock,kind,url,datetime.now(timezone.utc),status,content_type,
                     acceptance,prefix,hashlib.sha256(prefix).hexdigest() if prefix is not None else None,error])
                print(accession,kind,status,acceptance,flush=True)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        con.execute('COPY probes TO ? (FORMAT PARQUET,COMPRESSION ZSTD)',[str(args.output)])
    print('Saved source probes:',args.output,flush=True)


if __name__=='__main__':
    main()
