#!/bin/bash
# runs run_jobs.sh, then writes SHA256SUMS after every other write (run.out, STATUS, logs)
cd /home/ai-user/sinv/runs/20261117-110726-convbudget-srv
PAR=3 bash ~/fixb/run_jobs.sh /home/ai-user/sinv/runs/20261117-110726-convbudget-srv /home/ai-user/sinv/runs/20261117-110726-convbudget-srv/jobs-in.txt > /home/ai-user/sinv/runs/20261117-110726-convbudget-srv/run.out 2>&1
(cd /home/ai-user/sinv/runs/20261117-110726-convbudget-srv && find . -type f ! -name SHA256SUMS -printf "%P\0" | sort -z | xargs -0 sha256sum) > /home/ai-user/sinv/runs/20261117-110726-convbudget-srv/SHA256SUMS
