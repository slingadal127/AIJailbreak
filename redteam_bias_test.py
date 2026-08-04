from redteam_core import run_sweep
from redteam_bias import run_bias_audit

# repeats=5 gives enough counts for a valid chi-square (60 sweeps total)
report = run_bias_audit(run_sweep, repeats=5)
print("Parity:", report["parity_verdict"])
print(report["interpretation"])
# Saved to bias_audit_YYYYMMDD.json