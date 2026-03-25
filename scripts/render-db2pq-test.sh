#!/bin/sh
set -eu

quarto render db2pq_test/ibis_to_pq.qmd \
  --output-dir ../_site/db2pq_test \
  --execute-dir db2pq_test
