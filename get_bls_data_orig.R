library(plyr)
library(stringr)

######### FIRST, PREPROCESS RAW BLS DATA ##############
bls_process <- function(blsdata_yr){
  blsdata_yr$industry_code <- as.character(blsdata_yr$industry_code)
  blsdata_yr$industry_code[which(blsdata_yr$industry_code=="31-33")] <- "31";
  blsdata_yr$industry_code[which(blsdata_yr$industry_code=="44-45")] <- "44";
  blsdata_yr$industry_code[which(blsdata_yr$industry_code=="48-49")] <- "48";

  blsdata_yr$industry_code <- as.integer(blsdata_yr$industry_code)

  # now keep only 2-digit industry level observations...
  blsdata_yr <- blsdata_yr[which(blsdata_yr$industry_code < 100),]


  # and for now just keep the ownership codes for (a) total employment levels -- own_code = 0; and (b) total private sector employment -- own_code = 5


  blsdata_yr <- blsdata_yr[which((blsdata_yr$own_code==5)|(blsdata_yr$own_code==0)),]

  blsdata_yr$state_level_flag <- 1 * (blsdata_yr$agglvl_code > 49) * (blsdata_yr$agglvl_code < 60)
  blsdata_yr$county_level_flag <- 1 * (blsdata_yr$agglvl_code > 69) * (blsdata_yr$agglvl_code < 80)

  blsdata_yr

}

raw_data_dir <- path.expand(file.path(Sys.getenv("RAW_DATA_DIR"), "bls"))

bls01_in <- read.csv(unzip(str_glue("{raw_data_dir}/2001_annual_singlefile.zip"))); bls01 <- bls_process(bls01_in); rm(bls01_in)
bls02_in <- read.csv(unzip(str_glue("{raw_data_dir}/2002_annual_singlefile.zip"))); bls02 <- bls_process(bls02_in); rm(bls02_in)
bls03_in <- read.csv(unzip(str_glue("{raw_data_dir}/2003_annual_singlefile.zip"))); bls03 <- bls_process(bls03_in); rm(bls03_in)
bls04_in <- read.csv(unzip(str_glue("{raw_data_dir}/2004_annual_singlefile.zip"))); bls04 <- bls_process(bls04_in); rm(bls04_in)
bls05_in <- read.csv(unzip(str_glue("{raw_data_dir}/2005_annual_singlefile.zip"))); bls05 <- bls_process(bls05_in); rm(bls05_in)
bls06_in <- read.csv(unzip(str_glue("{raw_data_dir}/2006_annual_singlefile.zip"))); bls06 <- bls_process(bls06_in); rm(bls06_in)
bls07_in <- read.csv(unzip(str_glue("{raw_data_dir}/2007_annual_singlefile.zip"))); bls07 <- bls_process(bls07_in); rm(bls07_in)
bls08_in <- read.csv(unzip(str_glue("{raw_data_dir}/2008_annual_singlefile.zip"))); bls08 <- bls_process(bls08_in); rm(bls08_in)
bls09_in <- read.csv(unzip(str_glue("{raw_data_dir}/2009_annual_singlefile.zip"))); bls09 <- bls_process(bls09_in); rm(bls09_in)
bls10_in <- read.csv(unzip(str_glue("{raw_data_dir}/2010_annual_singlefile.zip"))); bls10 <- bls_process(bls10_in); rm(bls10_in)
bls11_in <- read.csv(unzip(str_glue("{raw_data_dir}/2011_annual_singlefile.zip"))); bls11 <- bls_process(bls11_in); rm(bls11_in)
bls12_in <- read.csv(unzip(str_glue("{raw_data_dir}/2012_annual_singlefile.zip"))); bls12 <- bls_process(bls12_in); rm(bls12_in)
bls13_in <- read.csv(unzip(str_glue("{raw_data_dir}/2013_annual_singlefile.zip"))); bls13 <- bls_process(bls13_in); rm(bls13_in)
bls14_in <- read.csv(unzip(str_glue("{raw_data_dir}/2014_annual_singlefile.zip"))); bls14 <- bls_process(bls14_in); rm(bls14_in)
bls15_in <- read.csv(unzip(str_glue("{raw_data_dir}/2015_annual_singlefile.zip"))); bls15 <- bls_process(bls15_in); rm(bls15_in)
bls16_in <- read.csv(unzip(str_glue("{raw_data_dir}/2016_annual_singlefile.zip"))); bls16 <- bls_process(bls16_in); rm(bls16_in)
bls17_in <- read.csv(unzip(str_glue("{raw_data_dir}/2017_annual_singlefile.zip"))); bls17 <- bls_process(bls17_in); rm(bls17_in)
bls18_in <- read.csv(unzip(str_glue("{raw_data_dir}/2018_annual_singlefile.zip"))); bls18 <- bls_process(bls18_in); rm(bls18_in)
bls19_in <- read.csv(unzip(str_glue("{raw_data_dir}/2019_annual_singlefile.zip"))); bls19 <- bls_process(bls19_in); rm(bls19_in)


bls_all <- rbind(bls01, bls02, bls03, bls04, bls05, bls06, bls07, bls08,
                 bls09, bls10, bls11, bls12, bls13,
                 bls14, bls15, bls16, bls17, bls18, bls19)

bls_state <- bls_all[which(bls_all$state_level_flag==1),]
bls_county <- bls_all[which(bls_all$county_level_flag==1),]
bls_national <- bls_all[which(bls_all$agglvl_code==10),]

write.csv(bls_state, str_glue("{raw_data_dir}/bls_state.csv"),row.names=FALSE)
write.csv(bls_county, str_glue("{raw_data_dir}/bls_county.csv"),row.names=FALSE)
write.csv(bls_national, str_glue("{raw_data_dir}/bls_national.csv"),row.names=FALSE)
