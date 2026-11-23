#!/bin/bash
# runs run_jobs.sh, then writes SHA256SUMS after every other write (run.out, STATUS, logs)
cd /home/ai-user/sinv/runs/20261117-111223-convbudget-stock-srv
PAR=3 bash ~/fixb/run_jobs.sh /home/ai-user/sinv/runs/20261117-111223-convbudget-stock-srv /home/ai-user/sinv/runs/20261117-111223-convbudget-stock-srv/jobs-in.txt > /home/ai-user/sinv/runs/20261117-111223-convbudget-stock-srv/run.out 2>&1
(cd /home/ai-user/sinv/runs/20261117-111223-convbudget-stock-srv && find . -type f ! -name SHA256SUMS -printf "%P\0" | sort -z | xargs -0 sha256sum) > /home/ai-user/sinv/runs/20261117-111223-convbudget-stock-srv/SHA256SUMS
