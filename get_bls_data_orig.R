library(plyr)
library(stringr)

raw_data_dir <- path.expand(file.path(Sys.getenv("RAW_DATA_DIR"), "qcew"))
data_dir <- path.expand(file.path(Sys.getenv("DATA_DIR"), "dlr"))

######### FIRST, PREPROCESS RAW BLS DATA ##############
bls_process <- function(year) {
  zipfile <- unzip(str_glue("{raw_data_dir}/{year}_annual_singlefile.zip"))
  blsdata_yr <- read.csv(zipfile)
  blsdata_yr$industry_code <- as.character(blsdata_yr$industry_code)
  blsdata_yr$industry_code[which(blsdata_yr$industry_code=="31-33")] <- "31";
  blsdata_yr$industry_code[which(blsdata_yr$industry_code=="44-45")] <- "44";
  blsdata_yr$industry_code[which(blsdata_yr$industry_code=="48-49")] <- "48";

  blsdata_yr$industry_code <- as.integer(blsdata_yr$industry_code)

  # now keep only 2-digit industry level observations...
  blsdata_yr <- blsdata_yr[which(blsdata_yr$industry_code < 100),]

  # and for now just keep the ownership codes for
  # (a) total employment levels -- own_code = 0; and
  # (b) total private sector employment -- own_code = 5
  blsdata_yr <- blsdata_yr[which((blsdata_yr$own_code==5)|(blsdata_yr$own_code==0)),]

  blsdata_yr$state_level_flag <- 1 * (blsdata_yr$agglvl_code > 49) * (blsdata_yr$agglvl_code < 60)
  blsdata_yr$county_level_flag <- 1 * (blsdata_yr$agglvl_code > 69) * (blsdata_yr$agglvl_code < 80)
  unlink(zipfile)
  blsdata_yr
}

bls_all <- rbind(lapply(2001:2019L, bls_process))

bls_state <- bls_all[which(bls_all$state_level_flag==1),]
bls_county <- bls_all[which(bls_all$county_level_flag==1),]
bls_national <- bls_all[which(bls_all$agglvl_code==10),]

write.csv(bls_state, str_glue("{data_dir}/bls_state.csv"),row.names=FALSE)
write.csv(bls_county, str_glue("{data_dir}/bls_county.csv"),row.names=FALSE)
write.csv(bls_national, str_glue("{data_dir}/bls_national.csv"),row.names=FALSE)
