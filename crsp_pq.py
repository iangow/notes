#!/usr/bin/env python3
from wrds2pg import wrds_to_parquet
wrds_to_parquet("dsedelist", "crsp", fix_missing=True,
                col_types = {'permno':'integer', 
                'permco': 'integer'})
                
wrds_to_parquet("mse", "crsp", fix_missing=True)

wrds_to_parquet("msf", "crsp", fix_missing=True,
                col_types = {'permno':'integer', 
                'permco':'integer'})
