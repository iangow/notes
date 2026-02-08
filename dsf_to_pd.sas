%let start_date = '01JAN2010'd;
%let end_date   = '29JUN2018'd;

proc sql;
  create table tickers as
  select permno, ticker
  from crsp.stocknames as s
  where ticker in ('AAPL', 'MSFT', 'INTC', 'AMZN', 'GS') and
    &end_date between namedt and nameenddt;
quit;

proc sql;
  create table dsf_sub as
  select
      t.ticker, d.date, d.prc, d.ret, d.retx
  from crsp.dsf as d
  inner join work.tickers as t
    on d.permno = t.permno
  where d.date between &start_date and &end_date
  order by t.ticker, d.date;
quit;

/* Pass 1: compute cumulative growth */
data dsf_g;
  set dsf_sub;
  by ticker;

  retain growth;
  if first.ticker then growth = 1;
  else growth = growth * (1 + retx);
run;

/* Pass 2: grab the last prc and last growth for each ticker */
data lastvals(keep=ticker prc_last growth_last);
  set dsf_g;
  by ticker;
  if last.ticker then do;
    prc_last = prc;
    growth_last = growth;
    output;
  end;
run;

/* Join back and compute adjusted price */
proc sql;
  create table dsf_adj as
  select
      g.ticker,
      g.date,
      /* adjusted price */
      (l.prc_last * g.growth / l.growth_last) as prc_adj
  from dsf_g as g
  inner join lastvals as l
    on g.ticker = l.ticker
  order by g.ticker, g.date;
quit;

proc export data=dsf_adj outfile=stdout dbms=csv;
run;
