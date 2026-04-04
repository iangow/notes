from pathlib import Path

import polars as pl
from era_pl import load_parquet


FIRST_DATE = pl.date(2010, 1, 1)
LAST_DATE = pl.date(2019, 12, 31)
DAYS_BEFORE = 20
DAYS_AFTER = 20
OUTPUT_PATH = Path("earn_annc_summ.parquet")


def build_earn_annc_summ() -> pl.DataFrame:
    fundq = load_parquet("fundq", "comp")
    ccmxpf_lnkhist = load_parquet("ccmxpf_lnkhist", "crsp")
    dsi = load_parquet("dsi", "crsp")
    dsf = load_parquet("dsf", "crsp")
    stocknames = load_parquet("stocknames", "crsp")

    earn_annc_dates = (
        fundq
        .filter(
            pl.col("indfmt") == "INDL",
            pl.col("datafmt") == "STD",
            pl.col("consol") == "C",
            pl.col("popsrc") == "D",
            pl.col("rdq").is_not_null(),
            pl.col("fqtr") == 4,
        )
        .select("gvkey", "datadate", "rdq")
        .filter(pl.col("datadate").is_between(FIRST_DATE, LAST_DATE))
    )

    ccm_link = (
        ccmxpf_lnkhist
        .filter(
            pl.col("linktype").is_in(["LC", "LU", "LS"]),
            pl.col("linkprim").is_in(["C", "P"]),
        )
        .rename({"lpermno": "permno"})
        .with_columns(
            linkenddt=pl.col("linkenddt").fill_null(pl.col("linkenddt").max()),
        )
    )

    trading_dates = (
        dsi
        .select("date")
        .sort("date")
        .with_row_index("td", offset=1)
        .with_columns(td=pl.col("td").cast(pl.Int32))
    )

    min_date = (
        trading_dates
        .select("date")
        .collect()
        .min()
        .item()
    )

    max_date = (
        trading_dates
        .select("date")
        .collect()
        .max()
        .item()
    )

    annc_dates = (
        pl.DataFrame(
            {
                "annc_date": pl.date_range(
                    min_date,
                    max_date,
                    interval="1d",
                    eager=True,
                )
            }
        )
        .lazy()
        .join(trading_dates, left_on="annc_date", right_on="date", how="left")
        .sort("annc_date")
        .with_columns(td=pl.col("td").backward_fill())
        .with_columns(td=pl.col("td").cast(pl.Int32))
    )

    mkt_rets = (
        dsf
        .join(dsi, on="date", how="inner")
        .with_columns(ret_mkt=pl.col("ret") - pl.col("vwretd"))
        .with_columns(pl.col("ret", "ret_mkt", "vol").cast(pl.Float64))
        .select("permno", "date", "ret", "ret_mkt", "vol")
    )

    nyse = (
        stocknames
        .filter(pl.col("exchcd") == 1)
        .select("permno", "namedt", "nameenddt")
    )

    earn_annc_links = (
        earn_annc_dates
        .join(ccm_link, on="gvkey", how="inner")
        .filter(pl.col("rdq").is_between(pl.col("linkdt"), pl.col("linkenddt")))
        .join(nyse, on="permno", how="inner")
        .filter(pl.col("rdq").is_between(pl.col("namedt"), pl.col("nameenddt")))
        .select("gvkey", "datadate", "rdq", "permno")
    )

    earn_annc_windows = (
        earn_annc_dates
        .join(annc_dates, left_on="rdq", right_on="annc_date", how="left")
        .rename({"td": "event_td"})
        .with_columns(
            start_td=pl.col("event_td") - DAYS_BEFORE,
            end_td=pl.col("event_td") + DAYS_AFTER,
        )
        .join(
            trading_dates.select(pl.all().name.prefix("start_")),
            on="start_td",
            how="inner",
        )
        .join(
            trading_dates.select(pl.all().name.prefix("end_")),
            on="end_td",
            how="inner",
        )
        .drop("start_td", "end_td")
    )

    earn_annc_window_permnos = (
        earn_annc_windows
        .join(earn_annc_links, on=["gvkey", "datadate", "rdq"], how="inner")
    )

    earn_annc_crsp = (
        mkt_rets
        .join(earn_annc_window_permnos, on="permno", how="inner")
        .filter(pl.col("date").is_between(pl.col("start_date"), pl.col("end_date")))
        .select("gvkey", "datadate", "rdq", "event_td", "date", "ret", "ret_mkt", "vol")
    )

    earn_annc_rets = (
        earn_annc_crsp
        .join(trading_dates, on="date", how="inner")
        .with_columns(relative_td=pl.col("td") - pl.col("event_td"))
    )

    earn_annc_vols = (
        earn_annc_rets
        .with_columns(avg_vol=pl.col("vol").mean().over("gvkey", "datadate"))
        .with_columns(
            rel_vol=pl.col("vol") / pl.col("avg_vol"),
            year=pl.col("datadate").dt.year(),
        )
    )

    return (
        earn_annc_vols
        .group_by("relative_td", "year")
        .agg(
            pl.len().alias("obs"),
            pl.col("ret", "ret_mkt", "rel_vol").mean().name.prefix("mean_"),
            pl.col("ret_mkt", "rel_vol").std(ddof=1).name.prefix("sd_"),
            pl.col("ret_mkt", "rel_vol").abs().mean().name.prefix("mad_"),
        )
        .sort("year", "relative_td")
        .collect()
    )


def main() -> None:
    earn_annc_summ = build_earn_annc_summ()
    earn_annc_summ.write_parquet(OUTPUT_PATH)
    print(f"Wrote {earn_annc_summ.height} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
