#!/bin/sh
set -eu

quarto render db2pq_test/ibis_to_pq.qmd \
  --output-dir ../_site/db2pq_test \
  --execute-dir db2pq_test

quarto render db2pq_test/local_engine_benchmark.qmd \
  --output-dir ../_site/db2pq_test \
  --execute-dir db2pq_test
